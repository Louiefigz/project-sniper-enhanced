import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import { objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { planObjectContentHash } from "@/lib/server/auto-edit-authority";
import {
  loadCutRepairPreparationSync,
} from "@/lib/server/cut-repair-preparation-store";
import { authorityKey } from "@/lib/server/producer-authority-files";
import { resolveProducerAuthorityHeadSync } from
  "@/lib/server/producer-revision-head";
import { parsePreparedMediaResult } from "./cut-repair-preparation-plan";
import { ensureAlternateTakeSelection } from
  "./cut-repair-alternate-take-runner";
import {
  cutRepairPreparationResponse,
  storePreparedCutRepairPackageSync,
} from "./cut-repair-preparation-package";
import { renderCutRepairPrivatePlan } from
  "./cut-repair-private-render";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";
import {
  runCutRepairPython,
  withCutRepairAnalysis,
  type CutRepairProcessResult,
} from "./cut-repair-route-runner";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";

const PREPARER = path.join(SCRIPTS_DIR, "producer", "edit", "cut_repair_prepare_media.py");
const PREPARATION_TIMEOUT_MS = 30 * 60 * 1000;

export interface CutRepairPreparationServices {
  existing: typeof existingPreparation;
  prepareNew: (
    producerDir: string,
    manifestPath: string,
    directive: CutRepairDirectiveV1,
  ) => Promise<Record<string, unknown>>;
  attachSelection: typeof attachAlternateTakeSelection;
}

function targetHash(directive: CutRepairDirectiveV1): string {
  return canonicalJsonSha256({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    target: directive.target,
  });
}
function realDirectory(directory: string): void {
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || realpathSync(directory) !== directory) {
    throw new Error("cut repair preparation staging must be a real directory");
  }
}
function stagingDirectory(
  producerDir: string,
  idempotencyKey: string,
): string {
  const root = path.join(producerDir, ".sniper-cut-repair-staging");
  realDirectory(root);
  const staging = path.join(root, authorityKey(idempotencyKey));
  realDirectory(staging);
  return staging;
}
function processValue(
  result: CutRepairProcessResult,
): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(result.stdout.trim());
  } catch {
    throw new Error(
      result.stderr.trim() || "cut repair media preparer returned no JSON");
  }
  const row = objectValue(value, "cut repair media preparer result");
  if (result.code !== 0) {
    throw new Error(
      typeof row.error === "string"
        ? row.error : result.stderr.trim() || "cut repair media prepare failed");
  }
  return row;
}

function assertAnalysisBindings(
  analysis: Record<string, unknown>,
  prepared: ReturnType<typeof parsePreparedMediaResult>,
): void {
  const selected = objectValue(
    analysis.recommendedCandidate, "recommended repair candidate");
  if (analysis.status !== "eligible"
      || analysis.parentRevisionHash !== prepared.parentRevisionHash
      || analysis.contextAuthorityHash !== prepared.contextAuthorityHash
      || selected.operationHash !== prepared.operationHash
      || selected.selectionPolicyHash !== prepared.selectionPolicyHash) {
    throw new Error("prepared media changed the deterministic selection");
  }
}

function existingPreparation(
  producerDir: string,
  directive: CutRepairDirectiveV1,
): Record<string, unknown> | null {
  if (!directive.idempotencyKey) {
    throw new Error("cut repair prepare requires idempotencyKey");
  }
  const stored = loadCutRepairPreparationSync(
    producerDir, directive.idempotencyKey, targetHash(directive));
  if (!stored) return null;
  if (resolveProducerAuthorityHeadSync(producerDir)
      !== stored.package.parentRevisionHash) {
    throw new Error("private review preparation was superseded by a newer edit");
  }
  return cutRepairPreparationResponse(stored, true);
}

async function prepareNew(
  producerDir: string,
  directive: CutRepairDirectiveV1,
  manifestPath: string,
  workspace: Parameters<
    Parameters<typeof withCutRepairAnalysis>[3]
  >[0],
): Promise<Record<string, unknown>> {
  const staging = stagingDirectory(producerDir, directive.idempotencyKey!);
  const process = await runCutRepairPython(
    PREPARER,
    [producerDir, workspace.directivePath, workspace.contextPath, staging],
    "cut repair private media preparation",
    PREPARATION_TIMEOUT_MS,
  );
  const prepared = parsePreparedMediaResult(processValue(process));
  assertAnalysisBindings(workspace.analysis, prepared);
  const context = objectValue(
    JSON.parse(readFileSync(workspace.contextPath, "utf8")),
    "cut repair context");
  const render = await renderCutRepairPrivatePlan({
    producerDir,
    stagingDir: staging,
    manifestPath,
    reviewPlan: prepared.reviewPlan,
    planObjectHash: prepared.reviewPlanHash,
    planContentHash: planObjectContentHash(prepared.reviewPlan)!,
    prepared,
  });
  const response = storePreparedCutRepairPackageSync({
    producerDir,
    directive,
    context,
    analysis: workspace.analysis,
    prepared,
    render,
    targetDirectiveHash: targetHash(directive),
  });
  return response;
}

async function attachAlternateTakeSelection(
  producerDir: string,
  manifestPath: string,
  directive: CutRepairDirectiveV1,
  response: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (typeof response.preparationHash !== "string") {
    throw new Error("stored cut repair preparation hash is absent");
  }
  const selection = await ensureAlternateTakeSelection({
    producerDir,
    preparationHash: response.preparationHash,
    manifestPath,
    request: directive.alternateTake,
  });
  return { ...response, alternateTakeSelection: selection };
}

function prepareNewLifecycle(
  producerDir: string,
  manifestPath: string,
  directive: CutRepairDirectiveV1,
): Promise<Record<string, unknown>> {
  return withCutRepairAnalysis(
    producerDir,
    manifestPath,
    directive,
    (workspace) => prepareNew(
      producerDir, directive, manifestPath, workspace),
  );
}

const DEFAULT_SERVICES: CutRepairPreparationServices = {
  existing: existingPreparation,
  prepareNew: prepareNewLifecycle,
  attachSelection: attachAlternateTakeSelection,
};

/** Build durable real diagnostic media without pretending it is promotable. */
export async function runCutRepairPreparation(
  producerDir: string,
  manifestPath: string,
  directive: CutRepairDirectiveV1,
  services: CutRepairPreparationServices = DEFAULT_SERVICES,
): Promise<Record<string, unknown>> {
  if (directive.mode !== "prepare") {
    throw new Error("cut repair preparation requires mode=prepare");
  }
  const response = services.existing(producerDir, directive)
    ?? await services.prepareNew(producerDir, manifestPath, directive);
  return services.attachSelection(
    producerDir, manifestPath, directive, response);
}
