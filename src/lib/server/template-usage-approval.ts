import {
  existsSync, lstatSync, readFileSync, realpathSync, rmSync,
} from "node:fs";
import path from "node:path";
import { SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { readProjectJson } from "@/app/api/_lib/workspace";
import { resolveLanes, type ProjectIntent } from "@/lib/producer/intent-presets";
import { atomicWriteJsonSync } from "./atomic-file";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import type { TemplateUsageAuthority } from "./template-usage-history";

export const TEMPLATE_USAGE_APPROVAL_FILE = ".sniper-template-usage-approved.json";
const TEMPLATE_CONTRACT = path.join(SCRIPTS_DIR, "producer", "template_usage_contract.py");
const OPERATOR_CONTRACT = path.join(SCRIPTS_DIR, "producer", "operator_intent_contract.py");
const SHA = /^[0-9a-f]{64}$/;

interface TemplateGateVerdict {
  ok: boolean;
  metrics?: Record<string, unknown>;
}

interface ApprovalInput {
  producerDir: string;
  planPath: string;
  manifestPath: string;
  transcriptsDir: string;
  templateUsage: TemplateUsageAuthority;
  verdict: TemplateGateVerdict;
  operatorIntentVerdict: TemplateGateVerdict;
}

interface DeliveryInput {
  producerDir: string;
  planPath: string;
  manifestPath: string;
  transcriptsDir?: string;
}

export interface TemplateUsageApproval {
  schemaVersion: 1;
  kind: "producer-template-usage-approval";
  planHash: string;
  planContentHash: string;
  manifestHash: string;
  transcriptDigest: string;
  contractHash: string;
  operatorIntentDigest: string;
  operatorIntentContractHash: string;
  historyPath: string;
  historyDigest: string;
  approvedAt: string;
  digest: string;
}

function hash(value: unknown): string {
  return canonicalJsonSha256(value);
}

function readJson(filePath: string): Record<string, unknown> {
  const value = JSON.parse(readFileSync(filePath, "utf8")) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${filePath} must contain a JSON object`);
  }
  return value as Record<string, unknown>;
}

function storedOperatorIntent(producerDir: string): ProjectIntent {
  const project = readProjectJson(path.dirname(path.resolve(producerDir)));
  const intent = project?.resolvedIntent ?? project?.intent;
  if (!intent || !["short", "longform"].includes(intent.mode)
      || !["trim", "light", "produced", "full"].includes(intent.scope)
      || !intent.lanes || typeof intent.lanes !== "object") {
    throw new Error("delivery needs a valid stored operator intent in project.json");
  }
  resolveLanes(intent.scope, intent.lanes);
  return intent;
}

function operatorIntentAuthority(producerDir: string): Omit<ProjectIntent, "preset"> {
  const authority = { ...storedOperatorIntent(producerDir) };
  delete authority.preset;
  return authority;
}

export function templateUsageApprovalRequired(producerDir: string): boolean {
  const intent = storedOperatorIntent(producerDir);
  return ["produced", "full"].includes(intent.scope)
    && resolveLanes(intent.scope, intent.lanes).graphics === "auto";
}

function transcriptDigest(manifestPath: string, transcriptsDir: string): string {
  const manifest = readJson(manifestPath);
  const sources = Array.isArray(manifest.sources) ? manifest.sources : [];
  const rows = sources.map((value, index) => {
    const source = value as Record<string, unknown>;
    const transcript = source.transcriptPath;
    if (transcript == null) return [String(source.id ?? index), null, null];
    if (typeof transcript !== "string" || !transcript) {
      throw new Error(`manifest source ${String(source.id ?? index)} has an invalid transcriptPath`);
    }
    const resolved = path.isAbsolute(transcript) ? transcript : path.join(transcriptsDir, transcript);
    const digest = fileSha256(resolved);
    if (!digest) throw new Error(`referenced transcript is missing: ${resolved}`);
    return [String(source.id ?? index), transcript, digest];
  });
  return hash(rows);
}

function historyDigest(producerDir: string, filePath: string): string {
  const root = path.resolve(producerDir, ".sniper-learning", "runs");
  const target = path.resolve(filePath);
  const relative = path.relative(root, target);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("template usage history path escapes its controller-owned run directory");
  }
  if (!existsSync(target) || lstatSync(target).isSymbolicLink() || !lstatSync(target).isFile()
      || path.relative(realpathSync(root), realpathSync(target)).startsWith("..")) {
    throw new Error("template usage history is missing or unsafe");
  }
  const history = readJson(target);
  const found = history.digest;
  const core = { ...history };
  delete core.digest;
  if (typeof found !== "string" || !SHA.test(found) || found !== hash(core)) {
    throw new Error("template usage history digest is invalid");
  }
  return found;
}

function content(input: DeliveryInput) {
  const plan = readJson(input.planPath);
  const transcriptsDir = input.transcriptsDir ?? path.dirname(input.manifestPath);
  const planHash = fileSha256(input.planPath);
  const manifestHash = fileSha256(input.manifestPath);
  const contractHash = fileSha256(TEMPLATE_CONTRACT);
  const operatorIntentContractHash = fileSha256(OPERATOR_CONTRACT);
  if (!planHash || !manifestHash || !contractHash || !operatorIntentContractHash) {
    throw new Error("template usage approval inputs or gate implementation are missing");
  }
  const operatorIntentDigest = hash(operatorIntentAuthority(input.producerDir));
  return {
    planHash,
    planContentHash: hash(plan),
    manifestHash,
    transcriptDigest: transcriptDigest(input.manifestPath, transcriptsDir),
    contractHash,
    operatorIntentDigest,
    operatorIntentContractHash,
  };
}

export function templateUsageApprovalPath(producerDir: string): string {
  return path.join(producerDir, TEMPLATE_USAGE_APPROVAL_FILE);
}

export function clearTemplateUsageApproval(producerDir: string): void {
  rmSync(templateUsageApprovalPath(producerDir), { force: true });
}

/** Commit the exact controller-bound history that passed the deterministic gate. */
export function writeTemplateUsageApproval(input: ApprovalInput): void {
  if (!templateUsageApprovalRequired(input.producerDir)) {
    clearTemplateUsageApproval(input.producerDir);
    return;
  }
  const snapshotDigest = input.verdict.metrics?.snapshotDigest;
  if (!input.verdict.ok || snapshotDigest !== input.templateUsage.digest
      || !input.operatorIntentVerdict.ok) {
    throw new Error("template usage gate did not pass against its controller-bound history");
  }
  const foundHistory = historyDigest(input.producerDir, input.templateUsage.path);
  if (foundHistory !== input.templateUsage.digest) {
    throw new Error("template usage gate history no longer matches its authority");
  }
  const core = {
    schemaVersion: 1 as const,
    kind: "producer-template-usage-approval" as const,
    ...content(input),
    historyPath: input.templateUsage.path,
    historyDigest: foundHistory,
    approvedAt: new Date().toISOString(),
  };
  atomicWriteJsonSync(templateUsageApprovalPath(input.producerDir), {
    ...core, digest: hash(core),
  });
}

function validReceipt(value: unknown): value is TemplateUsageApproval {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Partial<TemplateUsageApproval>;
  const hashes = [row.planHash, row.planContentHash, row.manifestHash,
    row.transcriptDigest, row.contractHash, row.operatorIntentDigest,
    row.operatorIntentContractHash, row.historyDigest, row.digest];
  return row.schemaVersion === 1 && row.kind === "producer-template-usage-approval"
    && typeof row.historyPath === "string" && path.isAbsolute(row.historyPath)
    && typeof row.approvedAt === "string" && Number.isFinite(Date.parse(row.approvedAt))
    && hashes.every((item) => typeof item === "string" && SHA.test(item));
}

/** Produced/full delivery is impossible without current, tamper-evident history governance. */
export function assertTemplateUsageApprovalCurrent(input: DeliveryInput): void {
  if (!templateUsageApprovalRequired(input.producerDir)) return;
  const destination = templateUsageApprovalPath(input.producerDir);
  let receipt: TemplateUsageApproval;
  try {
    const value = JSON.parse(readFileSync(destination, "utf8")) as unknown;
    if (!validReceipt(value)) throw new Error("invalid receipt shape");
    receipt = value;
  } catch {
    throw new Error("produced/full delivery needs a current template-history review; review the saved plan first");
  }
  const { digest, ...core } = receipt;
  const current = content(input);
  const foundHistory = historyDigest(input.producerDir, receipt.historyPath);
  const currentValues = Object.entries(current) as Array<[keyof typeof current, string]>;
  if (digest !== hash(core) || foundHistory !== receipt.historyDigest
      || currentValues.some(([key, value]) => receipt[key] !== value)) {
    throw new Error("template-history approval is stale; review the current saved plan before delivery");
  }
}
