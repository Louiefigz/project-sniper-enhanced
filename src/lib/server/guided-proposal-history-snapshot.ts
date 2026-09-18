import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { AutoEditPipelineAuthority } from "@/app/api/producer/auto-edit/stream";

/** Snapshot bytes only: never current repository equivalence or permission to run old code. */
export function observeHistoricalProposalSnapshot(pipeline: AutoEditPipelineAuthority, compiler: Record<string, unknown>) {
  const observed = observeHistoricalPipelineSnapshot(pipeline);
  validateCompilerSnapshot(compiler, { pipeline, hashes: observed.hashes, sizes: observed.sizes });
  return { fileCount: observed.hashes.size, observedBytes: observed.total, pipelineDigest: pipeline.digest };
}

/** Exact historical code bytes only; cleanup does not need mutable proposal metadata or current source media. */
export function observeHistoricalPipelineSnapshot(pipeline: AutoEditPipelineAuthority) {
  if (!pipeline || pipeline.schemaVersion !== 1 || !Array.isArray(pipeline.files) || !pipeline.files.length || pipeline.files.length > 16384) throw new Error("Historical pinned pipeline is unavailable or unbounded");
  const lock = readCutPreviewObject(pipeline.lockPath).value;
  exactKeys(lock, ["schemaVersion", "state", "runId", "digest", "files"], ["schemaVersion", "state", "runId", "digest", "files"], "historical pipeline lock");
  if (lock.schemaVersion !== 1 || lock.state !== "pinned" || lock.runId !== pipeline.runId || lock.digest !== pipeline.digest
      || canonicalJsonSha256(lock.files) !== pipeline.digest || canonicalJsonSha256(pipeline.files) !== pipeline.digest) throw new Error("Historical pipeline envelope differs from its immutable lock");
  const hashes = new Map<string, string>(), sizes = new Map<string, number>(); let total = 0;
  for (const row of pipeline.files) {
    if (!row || typeof row.path !== "string" || !row.path || path.isAbsolute(row.path) || row.path.split(/[\\/]/u).some((part) => !part || part === "." || part === "..")
        || hashes.has(row.path)) throw new Error("Historical snapshot has unsafe or duplicate paths");
    sha256(row.hash, "historical source hash");
    const observed = observeCutPreviewFile(path.join(pipeline.snapshotRoot, ...row.path.split("/")), Math.min(64 * 1024 * 1024, 512 * 1024 * 1024 - total));
    total += observed.sizeBytes;
    if (total > 512 * 1024 * 1024 || observed.sha256 !== row.hash) throw new Error("Historical snapshot bytes changed or exceed512 MiB");
    hashes.set(row.path, row.hash); sizes.set(row.path, observed.sizeBytes);
  }
  return { hashes, sizes, total };
}

function validateCompilerSnapshot(compiler: Record<string, unknown>, held: {
  pipeline: AutoEditPipelineAuthority; hashes: Map<string, string>; sizes: Map<string, number>;
}) {
  const keys = ["files", "totalBytes", "scope", "runtime", "schemaHash", "schema"];
  exactKeys(compiler, keys, keys, "historical compiler closure");
  if (compiler.scope !== "captured-ts-source-and-runtime-config-not-built-bundle" || !Array.isArray(compiler.files)
      || !compiler.files.length || compiler.files.length > 4096 || !Number.isSafeInteger(compiler.totalBytes)
      || Number(compiler.totalBytes) <= 0 || Number(compiler.totalBytes) > 32 * 1024 * 1024) throw new Error("Historical compiler closure is malformed");
  historicalRuntime(compiler.runtime);
  const selected = new Set<string>(); let selectedBytes = 0;
  for (const value of compiler.files) {
    const row = objectValue(value, "historical compiler file"); exactKeys(row, ["name", "sha256"], ["name", "sha256"], "historical compiler file");
    if (typeof row.name !== "string" || selected.has(row.name) || held.hashes.get(row.name) !== row.sha256) throw new Error("Historical compiler file is outside its pinned snapshot");
    selected.add(row.name); selectedBytes += held.sizes.get(row.name)!;
  }
  if (selectedBytes !== compiler.totalBytes) throw new Error("Historical compiler byte count differs from actual pinned files");
  if ([...held.hashes.keys()].some((name) => /^src\/.*\.tsx?$/u.test(name) && !selected.has(name))) throw new Error("Historical compiler omitted captured TS source");
  const schema = objectValue(compiler.schema, "historical compiler schema"), version = objectValue(objectValue(schema.properties, "schema properties").schemaVersion, "schema version").const;
  if (typeof version !== "number" || ![2, 3, 4, 5, 6, 7, 8, 9, 10].includes(version)) throw new Error("Unsupported historical proposal schema");
  const schemaName = `schemas/producer/treatment-proposal-v${version}.schema.json`;
  const observed = readCutPreviewObject(path.join(held.pipeline.snapshotRoot, schemaName));
  if (!selected.has(schemaName) || held.hashes.get(schemaName) !== compiler.schemaHash || observed.sha256 !== compiler.schemaHash
      || canonicalJsonSha256(observed.value) !== canonicalJsonSha256(schema)) throw new Error("Historical compiler schema snapshot changed");
}

/** Validate recorded identity without equating it to the observer's newer runtime. */
function historicalRuntime(value: unknown): void {
  const runtime = objectValue(value, "historical compiler runtime"), keys = ["node", "v8", "platform", "arch"];
  exactKeys(runtime, keys, keys, "historical compiler runtime");
  if (keys.some((key) => typeof runtime[key] !== "string" || !String(runtime[key]).trim() || String(runtime[key]).length > 128)) {
    throw new Error("Historical compiler runtime metadata is malformed");
  }
}
