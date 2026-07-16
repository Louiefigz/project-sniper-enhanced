import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import type {
  AutoEditCtx,
  AutoEditPipelineAuthority,
  PipelineAuthorityFile,
} from "@/app/api/producer/auto-edit/stream";
import { prepareAutoEditDoctrineContext } from "./auto-edit-doctrine";

const SCHEMA_VERSION = 1 as const;
const SHA256 = /^[0-9a-f]{64}$/;
const LEARNING_DIR = ".sniper-learning";
const EXTENSIONS = /\.(?:py|ts|tsx|js|json|html|css|md|svg|png|jpe?g)$/i;
const MEDIA = /\.(?:mov|mp4|wav|mp3|pyc)$/i;
const REQUIRED_BINARY_ASSETS = new Map([
  ["scripts/producer/audio/models/bd.rnnn",
    "ae3f7411e1e6a884f839a4a145c394408398f09854dbc1216ee02faafc98a17b"],
]);
const EXCLUDED = new Set([
  "__pycache__", "__tests__", "node_modules", "renders", "cache", "tests", "docs",
  "study",
]);

interface CapturedFile extends PipelineAuthorityFile {
  bytes: Buffer;
}

interface PipelineLock {
  schemaVersion: typeof SCHEMA_VERSION;
  state: "pinned";
  runId: string;
  digest: string;
  files: PipelineAuthorityFile[];
}

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

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => compareText(left, right))
    .map(([key, item]) => [key, stableValue(item)]));
}

function stableHash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(stableValue(value))).digest("hex");
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

function logicalPath(root: string, filePath: string): string {
  return path.relative(root, filePath).split(path.sep).join("/");
}

function excluded(relative: string): boolean {
  return relative.split("/").some((part) => EXCLUDED.has(part)) || MEDIA.test(relative);
}

function walk(root: string, item: string): string[] {
  if (!existsSync(item)) return [];
  const relative = logicalPath(root, item);
  if (excluded(relative)) return [];
  const stat = lstatSync(item);
  if (stat.isSymbolicLink()) return [];
  if (stat.isFile()) {
    return EXTENSIONS.test(item) || REQUIRED_BINARY_ASSETS.has(relative) ? [item] : [];
  }
  if (!stat.isDirectory()) return [];
  return readdirSync(item).sort().flatMap((name) => walk(root, path.join(item, name)));
}

function sourceRoots(root: string): string[] {
  return [
    path.join(root, "scripts", "producer"),
    path.join(root, "templates", "motion"),
    path.join(root, "src", "app", "api", "producer", "auto-edit"),
    path.join(root, "src", "app", "api", "producer", "ai-edit"),
    path.join(root, "src", "app", "api", "producer", "live-build"),
    path.join(root, "src", "app", "api", "producer", "palmier"),
    path.join(root, "src", "app", "api", "_lib"),
    path.join(root, "src", "lib", "producer"),
    path.join(root, "src", "lib", "server"),
    path.join(root, "package.json"),
    path.join(root, "package-lock.json"),
  ];
}

function captureFiles(root: string): CapturedFile[] {
  const paths = [...new Set(sourceRoots(root).flatMap((item) => walk(root, item)))].sort();
  const captured = paths.map((filePath) => {
    const bytes = readFileSync(filePath);
    return { path: logicalPath(root, filePath), hash: bytesHash(bytes), bytes };
  });
  const present = new Map(captured.map((row) => [row.path, row.hash]));
  for (const [required, expectedHash] of REQUIRED_BINARY_ASSETS) {
    const actualHash = present.get(required);
    if (!actualHash) throw new Error(`Required Producer pipeline asset is missing: ${required}`);
    if (actualHash !== expectedHash) {
      throw new Error(`Required Producer pipeline asset failed verification: ${required}`);
    }
  }
  return captured;
}

function safeRunId(value: string): string {
  const safe = value.replace(/[^a-zA-Z0-9._-]/g, "_").slice(-96);
  if (!safe) throw new Error("pipeline run id is empty");
  return safe;
}

function writeTree(staging: string, files: CapturedFile[], lock: PipelineLock): void {
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
  const captured = captureFiles(root);
  const files = captured.map(({ path: filePath, hash }) => ({ path: filePath, hash }));
  const lock: PipelineLock = {
    schemaVersion: SCHEMA_VERSION, state: "pinned", runId: stableRunId,
    digest: stableHash(files), files,
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

function parseLock(authority: AutoEditPipelineAuthority): PipelineLock {
  if (!path.isAbsolute(authority.lockPath) || !existsSync(authority.lockPath)) {
    throw new Error("Pinned Producer pipeline lock is missing");
  }
  const value: unknown = JSON.parse(readFileSync(authority.lockPath, "utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Pinned Producer pipeline lock is invalid");
  }
  const lock = value as PipelineLock;
  const valid = lock.schemaVersion === SCHEMA_VERSION && lock.state === "pinned"
    && typeof lock.runId === "string" && SHA256.test(lock.digest) && Array.isArray(lock.files);
  if (!valid) throw new Error("Pinned Producer pipeline lock is invalid");
  return lock;
}

function verifyFiles(authority: AutoEditPipelineAuthority, files: PipelineAuthorityFile[]): void {
  const seen = new Set<string>();
  for (const row of files) {
    const valid = row && typeof row.path === "string" && row.path
      && !row.path.startsWith("/") && !row.path.split("/").includes("..")
      && typeof row.hash === "string" && SHA256.test(row.hash) && !seen.has(row.path);
    if (!valid) throw new Error("Pinned Producer pipeline receipt is invalid");
    seen.add(row.path);
    const copy = path.join(authority.snapshotRoot, ...row.path.split("/"));
    if (!existsSync(copy) || !lstatSync(copy).isFile() || bytesHash(readFileSync(copy)) !== row.hash) {
      throw new Error(`Pinned Producer pipeline copy was changed: ${row.path}`);
    }
  }
}

/** Restore a saved run without consulting mutable repository source. */
export function restoreAutoEditPipeline(
  expected: AutoEditPipelineAuthority,
): AutoEditPipelineAuthority {
  if (expected.schemaVersion !== SCHEMA_VERSION || !path.isAbsolute(expected.snapshotRoot)) {
    throw new Error("Pinned Producer pipeline envelope is invalid");
  }
  const lock = parseLock(expected);
  const sorted = [...lock.files].sort((left, right) => compareText(left.path, right.path));
  if (stableHash(sorted) !== lock.digest || lock.digest !== expected.digest
      || lock.runId !== expected.runId || stableHash(expected.files) !== stableHash(sorted)) {
    throw new Error("Pinned Producer pipeline authority does not match its receipt");
  }
  verifyFiles(expected, sorted);
  return { ...expected, files: sorted };
}

export function pipelineAuthorityPath(ctx: AutoEditCtx, relative: string): string {
  const root = ctx.pipeline ? restoreAutoEditPipeline(ctx.pipeline).snapshotRoot : repositoryRoot();
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
    ? restoreAutoEditPipeline(input.savedPipeline)
    : captureAutoEditPipeline(doctrineCtx, input.runId);
  return { ...doctrineCtx, pipeline };
}
