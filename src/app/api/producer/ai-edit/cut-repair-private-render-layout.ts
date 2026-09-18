import { randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { planObjectContentHash } from "@/lib/server/auto-edit-authority";
import {
  editorReadyRenderGraphArgs,
} from "@/lib/server/current-render-graph-command";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";
import {
  parsePreparedMediaResult,
  type PreparedMediaResult,
} from "./cut-repair-preparation-plan";

const RENDER = path.join(SCRIPTS_DIR, "producer", "render.py");
const ASSEMBLE = path.join(SCRIPTS_DIR, "producer", "assemble.py");

export interface CutRepairPrivateRenderInput {
  producerDir: string;
  stagingDir: string;
  manifestPath: string;
  reviewPlan: Record<string, unknown>;
  planObjectHash: string;
  planContentHash: string;
  prepared?: PreparedMediaResult | null;
}

export interface PrivateRenderLayout {
  artifactDir: string;
  workDir: string;
  outputPlan: string;
  sourcePlan: string;
  preparedPath: string | null;
  basePath: string;
  candidatePath: string;
  baseArgs: string[];
  assembleArgs: string[];
}

export interface ReopenedPrivateRender {
  layout: PrivateRenderLayout;
  prepared: PreparedMediaResult | null;
}

function realDirectory(directory: string): void {
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || realpathSync(directory) !== directory) {
    throw new Error("cut repair private render path must be a real directory");
  }
}

function assertStagingAuthority(input: CutRepairPrivateRenderInput): void {
  const producer = realpathSync(input.producerDir);
  const stagingRoot = path.join(producer, ".sniper-cut-repair-staging");
  const staging = path.resolve(input.stagingDir);
  if (producer !== path.resolve(input.producerDir)
      || staging !== input.stagingDir
      || !staging.startsWith(`${stagingRoot}${path.sep}`)
      || realpathSync(staging) !== staging) {
    throw new Error(
      "cut repair private render escaped controller-owned staging");
  }
}

function assertPlanIdentity(input: CutRepairPrivateRenderInput): void {
  if (canonicalJsonSha256(input.reviewPlan) !== input.planObjectHash
      || planObjectContentHash(input.reviewPlan) !== input.planContentHash) {
    throw new Error(
      "cut repair review plan exact and semantic identities disagree");
  }
}

function planInputPath(
  input: CutRepairPrivateRenderInput,
  root: string,
): string {
  const directory = path.join(root, "plan-input");
  realDirectory(directory);
  const planPath = path.join(directory, "edit_plan.json");
  if (!existsSync(planPath)) atomicWriteJsonSync(planPath, input.reviewPlan);
  const observed = JSON.parse(readFileSync(planPath, "utf8")) as unknown;
  if (canonicalJsonSha256(observed) !== input.planObjectHash) {
    throw new Error("cut repair private input plan changed exact identity");
  }
  return planPath;
}

function preparedInputPath(
  root: string,
  prepared: PreparedMediaResult,
): string {
  const directory = path.join(root, "plan-input");
  realDirectory(directory);
  const preparedPath = path.join(
    directory, "cut_repair_prepared_media.json");
  if (!existsSync(preparedPath)) {
    atomicWriteJsonSync(preparedPath, prepared.preparedMedia);
  }
  const observed = JSON.parse(readFileSync(preparedPath, "utf8")) as unknown;
  if (canonicalJsonSha256(observed)
      !== canonicalJsonSha256(prepared.preparedMedia)) {
    throw new Error("cut repair private prepared media changed identity");
  }
  return preparedPath;
}

function reopenedPrepared(
  input: CutRepairPrivateRenderInput,
): PreparedMediaResult | null {
  if (!input.prepared) {
    if (input.reviewPlan.cutRepairPicturePlanAuthority !== undefined) {
      throw new Error("picture repair private render lacks prepared authority");
    }
    return null;
  }
  const prepared = parsePreparedMediaResult(input.prepared.preparedMedia);
  if (prepared.reviewPlanHash !== input.planObjectHash
      || canonicalJsonSha256(prepared.reviewPlan) !== input.planObjectHash
      || planObjectContentHash(prepared.reviewPlan) !== input.planContentHash) {
    throw new Error("private render prepared media binds another review plan");
  }
  return prepared;
}

function privateRenderLayout(
  input: CutRepairPrivateRenderInput,
  prepared: PreparedMediaResult | null,
): PrivateRenderLayout {
  assertStagingAuthority(input);
  const root = path.join(
    input.stagingDir, "plan-render", input.planObjectHash);
  const artifactDir = path.join(root, "artifacts");
  const workDir = path.join(root, `work-${randomUUID()}`);
  [path.join(input.stagingDir, "plan-render"), root,
    artifactDir, workDir].forEach(realDirectory);
  const outputPlan = path.join(artifactDir, "edit_plan.json");
  const basePath = path.join(artifactDir, "base_final.mp4");
  const candidatePath = path.join(artifactDir, "final.mp4");
  const sourcePlan = planInputPath(input, root);
  const commands = editorReadyRenderGraphArgs({
    producerDir: input.producerDir, artifactDir,
    sourcePlanPath: sourcePlan, outputPlanPath: outputPlan,
    manifestPath: input.manifestPath, basePath, outputPath: candidatePath,
    fingerprintPath: path.join(artifactDir, "base.fingerprint.json"),
    workDir, renderScript: RENDER, assembleScript: ASSEMBLE,
    deferActive: true,
  });
  return {
    artifactDir, workDir, outputPlan, sourcePlan,
    preparedPath: prepared ? preparedInputPath(root, prepared) : null,
    basePath, candidatePath,
    baseArgs: commands.baseArgs, assembleArgs: commands.assembleArgs,
  };
}

/** Reopen Python output and build only canonical controller-owned paths. */
export function buildCutRepairPrivateRenderLayout(
  input: CutRepairPrivateRenderInput,
): ReopenedPrivateRender {
  assertPlanIdentity(input);
  const prepared = reopenedPrepared(input);
  return { prepared, layout: privateRenderLayout(input, prepared) };
}
