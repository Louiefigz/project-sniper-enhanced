import { assertVisualSourceSnapshot, VISUAL_SOURCE_POLICY_PATH } from "@/lib/producer/visual-source-policy";
import { createHash, randomUUID } from "node:crypto";
import {
  existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync,
  rmSync, writeFileSync,
} from "node:fs";
import path from "node:path";
import type {
  AutoEditCtx,
  AutoEditPipelineAuthority,
  PipelineAuthorityFile,
} from "@/app/api/producer/auto-edit/stream";
import { prepareAutoEditDoctrineContext } from "./auto-edit-doctrine";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  assertPipelineAssetClosure,
  capturePipelineAssets,
  type CapturedPipelineFile,
} from "./auto-edit-pipeline-assets";
import {
  readPipelineLock,
  verifyPipelineSnapshot,
  type PipelineLock,
} from "./auto-edit-pipeline-snapshot";

const SCHEMA_VERSION = 1 as const;
const SHA256 = /^[0-9a-f]{64}$/;
const LEARNING_DIR = ".sniper-learning";

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

export interface RunAuthorityInput {
  ctx: AutoEditCtx;
  runId: string;
  resume: boolean;
  savedDoctrine?: AutoEditCtx["doctrine"];
  savedPipeline?: AutoEditPipelineAuthority;
}

export function validAutoEditPipelineAuthority(
  value: unknown,
): value is AutoEditPipelineAuthority {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Partial<AutoEditPipelineAuthority>;
  return item.schemaVersion === SCHEMA_VERSION && typeof item.runId === "string"
    && typeof item.digest === "string" && SHA256.test(item.digest)
    && typeof item.snapshotRoot === "string" && path.isAbsolute(item.snapshotRoot)
    && typeof item.lockPath === "string" && path.isAbsolute(item.lockPath)
    && Array.isArray(item.files);
}

function bytesHash(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function repositoryRoot(): string {
  let current = path.resolve(process.cwd());
  for (;;) {
    if (existsSync(path.join(current, "scripts", "producer"))) return current;
    const parent = path.dirname(current);
    if (parent === current) throw new Error("Producer repository root was not found");
    current = parent;
  }
}

export function runtimeRepositoryRoot(): string {
  const configured = process.env.SNIPER_RUNTIME_REPO_ROOT;
  if (!configured) return repositoryRoot();
  if (!path.isAbsolute(configured) || path.normalize(configured) !== configured
      || realpathSync(configured) !== configured || !lstatSync(configured).isDirectory()) {
    throw new Error("Installed Producer runtime root is not canonical");
  }
  return configured;
}

let installedIdentity: {
  root: string;
  digest: string;
  files: PipelineAuthorityFile[];
} | null = null;

function installedPipelineIdentity(): {
  digest: string;
  files: PipelineAuthorityFile[];
} {
  const root = runtimeRepositoryRoot();
  if (!installedIdentity || installedIdentity.root !== root) {
    const files = capturePipelineAssets(root)
      .map(({ path: filePath, hash }) => ({ path: filePath, hash }));
    installedIdentity = { root, files, digest: canonicalJsonSha256(files) };
  }
  return installedIdentity;
}

function safeRunId(value: string): string {
  const safe = value.replace(/[^a-zA-Z0-9._-]/g, "_").slice(-96);
  if (!safe) throw new Error("pipeline run id is empty");
  return safe;
}

function writeTree(
  staging: string,
  files: CapturedPipelineFile[],
  lock: PipelineLock,
): void {
  const filesRoot = path.join(staging, "files");
  for (const row of files) {
    const destination = path.join(filesRoot, ...row.path.split("/"));
    mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
    writeFileSync(destination, row.bytes, { flag: "wx", mode: 0o600 });
  }
  writeFileSync(path.join(staging, "pipeline-lock.json"), `${JSON.stringify(lock, null, 2)}\n`, {
    flag: "wx", mode: 0o600,
  });
}

function envelope(destination: string, lock: PipelineLock): AutoEditPipelineAuthority {
  return {
    schemaVersion: SCHEMA_VERSION,
    runId: lock.runId,
    digest: lock.digest,
    snapshotRoot: path.join(destination, "files"),
    lockPath: path.join(destination, "pipeline-lock.json"),
    files: lock.files,
  };
}

/** Capture the exact renderer, gate, and template bytes before worker launch. */
export function captureAutoEditPipeline(
  ctx: AutoEditCtx,
  runId: string,
  root = repositoryRoot(),
): AutoEditPipelineAuthority {
  const stableRunId = safeRunId(runId);
  const captured = capturePipelineAssets(root);
  const files = captured.map(({ path: filePath, hash }) => ({ path: filePath, hash }));
  const lock: PipelineLock = {
    schemaVersion: SCHEMA_VERSION, state: "pinned", runId: stableRunId,
    digest: canonicalJsonSha256(files), files,
  };
  const runs = path.join(ctx.dir, LEARNING_DIR, "runs");
  const destination = path.join(runs, stableRunId, "pipeline");
  const staging = path.join(runs, `.${stableRunId}.${randomUUID()}.pipeline.tmp`);
  if (existsSync(destination)) throw new Error(`Pipeline snapshot already exists for ${stableRunId}`);
  mkdirSync(staging, { recursive: true, mode: 0o700 });
  try {
    writeTree(staging, captured, lock);
    mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
    renameSync(staging, destination);
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  return envelope(destination, lock);
}

/** Restore a saved run without consulting mutable repository source. */
export function restoreAutoEditPipeline(
  expected: AutoEditPipelineAuthority,
): AutoEditPipelineAuthority {
  if (expected.schemaVersion !== SCHEMA_VERSION || !path.isAbsolute(expected.snapshotRoot)) {
    throw new Error("Pinned Producer pipeline envelope is invalid");
  }
  assertVisualSourceSnapshot(expected.files, bytesHash(readFileSync(path.join(repositoryRoot(), VISUAL_SOURCE_POLICY_PATH))));
  const lock = readPipelineLock(expected);
  const sorted = [...lock.files].sort((left, right) => compareText(left.path, right.path));
  assertPipelineAssetClosure(sorted);
  if (canonicalJsonSha256(sorted) !== lock.digest || lock.digest !== expected.digest
      || lock.runId !== expected.runId
      || canonicalJsonSha256(expected.files) !== canonicalJsonSha256(sorted)) {
    throw new Error("Pinned Producer pipeline authority does not match its receipt");
  }
  verifyPipelineSnapshot(expected, sorted);
  return { ...expected, files: sorted };
}

function expectedProjectPipelineRoot(
  producerDir: string,
  runId: string,
): string {
  return path.join(path.resolve(producerDir), LEARNING_DIR, "runs", safeRunId(runId), "pipeline");
}

/** Admit a pipeline only from its controller-owned project/run location. */
export function restoreProjectAutoEditPipeline(
  producerDir: string,
  expected: AutoEditPipelineAuthority,
): AutoEditPipelineAuthority {
  const declared = expectedProjectPipelineRoot(producerDir, expected.runId);
  const canonical = expectedProjectPipelineRoot(
    realpathSync(producerDir), expected.runId,
  );
  const snapshot = path.join(declared, "files");
  const lock = path.join(declared, "pipeline-lock.json");
  const canonicalSnapshot = path.join(canonical, "files");
  const canonicalLock = path.join(canonical, "pipeline-lock.json");
  const outside = path.resolve(expected.snapshotRoot) !== snapshot
    || path.resolve(expected.lockPath) !== lock
    || realpathSync(expected.snapshotRoot) !== canonicalSnapshot
    || realpathSync(expected.lockPath) !== canonicalLock;
  if (outside) {
    throw new Error("Pinned Producer pipeline is outside its controller-owned project run");
  }
  return restoreAutoEditPipeline(expected);
}

/** Execute only a snapshot whose complete identity equals this installed runtime. */
export function restoreExecutableProjectAutoEditPipeline(
  producerDir: string,
  expected: AutoEditPipelineAuthority,
): AutoEditPipelineAuthority {
  const restored = restoreProjectAutoEditPipeline(producerDir, expected);
  const installed = installedPipelineIdentity();
  if (restored.digest !== installed.digest
      || canonicalJsonSha256(restored.files) !== canonicalJsonSha256(installed.files)) {
    throw new Error("Pinned Producer pipeline is not the installed executable runtime");
  }
  return restored;
}

/** Return the trusted installed root after proving the project receipt matches it. */
export function executablePipelineRoot(
  producerDir: string,
  expected: AutoEditPipelineAuthority,
): string {
  restoreExecutableProjectAutoEditPipeline(producerDir, expected);
  return runtimeRepositoryRoot();
}

export function pipelineAuthorityPath(ctx: AutoEditCtx, relative: string): string {
  if (ctx.pipeline) assertVisualSourceSnapshot(ctx.pipeline.files, bytesHash(readFileSync(path.join(repositoryRoot(), VISUAL_SOURCE_POLICY_PATH))));
  const root = ctx.pipeline
    ? executablePipelineRoot(ctx.dir, ctx.pipeline)
    : runtimeRepositoryRoot();
  return path.join(root, ...relative.split("/"));
}

/** Pin or restore both immutable run-owned authority envelopes. */
export function prepareAutoEditRunContext(input: RunAuthorityInput): AutoEditCtx {
  if (input.resume && !input.savedPipeline) {
    throw new Error("checkpoint predates immutable pipeline locking");
  }
  const doctrineCtx = prepareAutoEditDoctrineContext({
    ctx: input.ctx, runId: input.runId, resume: input.resume, saved: input.savedDoctrine,
  });
  const pipeline = input.savedPipeline
    ? restoreExecutableProjectAutoEditPipeline(input.ctx.dir, input.savedPipeline)
    : captureAutoEditPipeline(doctrineCtx, input.runId);
  return { ...doctrineCtx, pipeline };
}
