import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { atomicCreateJsonSync } from "./atomic-file";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readBytes, decodeText, sha } from "@/app/api/producer/studio/import/files";
import { canonicalProducerDir } from "@/app/api/_lib/workspace";

export const POLICY = "sniper-private-project-source-observation-v1";
export const SHA = /^[a-f0-9]{64}$/u;
export interface GradeObservationRequest {
  dir: string; sourceId: string; expectedPlanHash: string; expectedManifestHash: string;
  declaration: Record<string, unknown>;
}
export interface GradeJobInput {
  schemaVersion: 1; policy: typeof POLICY; jobId: string; producerDir: string; sourceId: string;
  declaration: Record<string, unknown>; ownerPid: number; implementationSha256: string;
  expected: { planSha256: string; manifestSha256: string; projectSha256: string };
}
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a closed observation object");
  return value as Record<string, unknown>;
}
export function checkTime(deadline: bigint): void {
  if (process.hrtime.bigint() >= deadline) throw new Error("Full-source observation work budget expired");
}
export function privateDirectory(directory: string, create = false): string {
  if (create && !fs.existsSync(directory)) fs.mkdirSync(directory, { mode: 0o700 });
  const info = fs.lstatSync(directory);
  if (!info.isDirectory() || info.isSymbolicLink() || fs.realpathSync(directory) !== directory
      || info.uid !== process.getuid?.() || (info.mode & 0o077) !== 0) throw new Error("Unsafe private observation directory");
  return directory;
}
export function writeRecord(file: string, value: unknown): string {
  privateDirectory(path.dirname(file)); atomicCreateJsonSync(file, value); fs.chmodSync(file, 0o400);
  return sha(readBytes(file, 8 * 1024 * 1024));
}
export function readRecord(file: string): Record<string, unknown> {
  return object(JSON.parse(decodeText(readBytes(file, 8 * 1024 * 1024))));
}
/** Bound invalid nested data before canonicalization; no declaration defaults. */
function boundedDeclaration(value: unknown): Record<string, unknown> {
  const pending = [{ value, depth: 0 }]; let count = 0, chars = 0;
  while (pending.length) {
    const row = pending.pop()!;
    if (++count > 2048 || row.depth > 8) throw new Error("Observation declaration is too deeply nested or large");
    if (typeof row.value === "string") { chars += row.value.length; if (chars > 32000) throw new Error("Observation declaration text is too large"); continue; }
    if (row.value === null || typeof row.value === "number" || typeof row.value === "boolean") continue;
    if (typeof row.value !== "object") throw new Error("Observation declaration contains unsupported values");
    pending.push(...Object.values(row.value).map(value => ({ value, depth: row.depth + 1 })));
  }
  return object(JSON.parse(JSON.stringify(value)));
}
export function validateRequest(input: GradeObservationRequest): GradeObservationRequest {
  const row = object(input);
  if (Object.keys(row).sort().join() !== "declaration,dir,expectedManifestHash,expectedPlanHash,sourceId"
      || typeof row.dir !== "string" || row.dir.length > 2048 || row.dir.includes("\\") || row.dir.split("/").includes("..")
      || typeof row.sourceId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u.test(row.sourceId)
      || typeof row.expectedPlanHash !== "string" || !SHA.test(row.expectedPlanHash)
      || typeof row.expectedManifestHash !== "string" || !SHA.test(row.expectedManifestHash)) throw new Error("Invalid private observation request");
  return { ...input, dir: canonicalProducerDir(input.dir), declaration: boundedDeclaration(input.declaration) };
}
export function parents(dir: string) {
  return { planSha256: sha(readBytes(path.join(dir, "edit_plan.json"), 2 * 1024 * 1024)),
    manifestSha256: sha(readBytes(path.join(dir, "asset_manifest.json"), 2 * 1024 * 1024)),
    projectSha256: sha(readBytes(path.join(path.dirname(dir), "project.json"), 2 * 1024 * 1024)) };
}
/** Shared bounded code walk; caller-specific clock wrappers never replace its file/hash rules. */
function collectSourceInventory(root: string, check: () => void): { files: { path: string; sha256: string }[] } {
  const pending = [path.join(root, "scripts/producer")], paths: string[] = [];
  let count = 0;
  while (pending.length) {
    check(); const item = pending.pop()!;
    if (++count > 6000 || fs.realpathSync(item) !== item) throw new Error("Observation source inventory is unsafe or over budget");
    const info = fs.lstatSync(item);
    if (info.isFile()) { if (/\.(?:py|js|json)$/u.test(item)) paths.push(item); continue; }
    if (!info.isDirectory()) throw new Error("Observation source inventory contains a special file");
    pending.push(...fs.readdirSync(item).filter(name => !["tests", "__pycache__", "cache", "docs", "node_modules"].includes(name)).map(name => path.join(item, name)));
  }
  for (const name of ["grade-observation-store.ts", "grade-observation-process.ts", "grade-observation-service.ts", "grade-observation-resource.ts"])
    paths.push(path.join(root, "src/lib/server", name));
  const files = paths.sort().map(file => { check(); return { path: file, sha256: sha(readBytes(file, 8 * 1024 * 1024)) }; });
  if (files.length > 4000) throw new Error("Observation source inventory is too large");
  return { files };
}

/** Preserve the existing standalone caller's actual deadline and check order. */
export function sourceInventory(root: string, deadline: bigint) {
  return collectSourceInventory(root, () => checkTime(deadline));
}

/** Borrow the opening owner's original budget callback; no epoch conversion or new timer.
 * The final callback includes time spent reading/hashing the final code file.
 */
export function sourceInventoryUnderGuard(root: string, guard: () => void) {
  const result = collectSourceInventory(root, guard);
  guard();
  return result;
}
export function createJob(request: GradeObservationRequest, root: string, deadline: bigint) {
  const expected = parents(request.dir);
  if (expected.planSha256 !== request.expectedPlanHash || expected.manifestSha256 !== request.expectedManifestHash)
    throw new Error("Saved observation parents changed");
  const inventory = sourceInventory(root, deadline);
  const store = privateDirectory(path.join(request.dir, ".sniper-grade-observations"), true);
  const jobId = randomUUID(), directory = path.join(store, jobId);
  fs.mkdirSync(directory, { mode: 0o700 });
  const implementationSha256 = writeRecord(path.join(directory, "implementation.json"), inventory);
  const input: GradeJobInput = { schemaVersion: 1, policy: POLICY, jobId, producerDir: request.dir,
    sourceId: request.sourceId, declaration: request.declaration, ownerPid: process.pid, implementationSha256, expected };
  const inputHash = writeRecord(path.join(directory, "input.json"), input);
  return { input, inputHash, directory, inventoryHash: canonicalJsonSha256(inventory) };
}
