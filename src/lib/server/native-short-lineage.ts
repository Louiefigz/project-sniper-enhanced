/**
 * Immutable logical clip identity for rebuilt native Short revisions.
 *
 * The record lives in PROJECT-MANIFEST.json, outside the authored plan and its prebuild review:
 * it names which project a revision was rebuilt from, so preview discovery may consider that
 * ancestor's completed work. It grants nothing by itself. Every reuse still requires identical
 * content hashes, and Python re-verifies each ancestor's manifest bytes before trusting it.
 */
import { randomUUID } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";

export interface NativeShortLineageParent {
  path: string; projectHash: string; manifestSha256: string; clipId: string; generation: number;
}
export interface NativeShortLineage {
  schemaVersion: 1; clipId: string; generation: number; parent: NativeShortLineageParent | null;
}
export const MAX_LINEAGE_GENERATION = 64;
const CLIP = /^[0-9a-f]{32}$/u, SHA = /^[0-9a-f]{64}$/u;

function exact(value: unknown, keys: string[], label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join("\0") !== [...keys].sort().join("\0")) {
    throw new Error(`Native clip lineage ${label} has missing or unknown fields`);
  }
  return value as Record<string, unknown>;
}

function generation(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > MAX_LINEAGE_GENERATION) {
    throw new Error("Native clip lineage generation is outside its bound");
  }
  return value as number;
}

/** Validate one recorded lineage without trusting any filesystem path it names. */
export function assertNativeShortLineage(value: unknown): NativeShortLineage {
  const row = exact(value, ["schemaVersion", "clipId", "generation", "parent"], "record");
  if (row.schemaVersion !== 1 || typeof row.clipId !== "string" || !CLIP.test(row.clipId)) {
    throw new Error("Native clip lineage needs schema 1 and a 128-bit clip identity");
  }
  const own = generation(row.generation);
  if (row.parent === null) {
    if (own !== 0) throw new Error("Native root clip lineage must be generation 0");
    return { schemaVersion: 1, clipId: row.clipId, generation: 0, parent: null };
  }
  const parent = exact(row.parent, ["path", "projectHash", "manifestSha256", "clipId", "generation"], "parent");
  if (typeof parent.path !== "string" || !path.isAbsolute(parent.path) || path.resolve(parent.path) !== parent.path
      || typeof parent.projectHash !== "string" || !SHA.test(parent.projectHash)
      || typeof parent.manifestSha256 !== "string" || !SHA.test(parent.manifestSha256)
      || parent.clipId !== row.clipId || generation(parent.generation) + 1 !== own) {
    throw new Error("Native clip lineage parent is not a canonical same-clip predecessor");
  }
  return { schemaVersion: 1, clipId: row.clipId, generation: own, parent: { path: parent.path,
    projectHash: parent.projectHash, manifestSha256: parent.manifestSha256, clipId: row.clipId,
    generation: parent.generation as number } };
}

/**
 * A new root receives a fresh random clip; a revision inherits its verified parent's clip.
 * `readParent` must be the full cold project reader, so a changed parent cannot be adopted.
 */
export function nativeShortLineage(parent: string | undefined, readParent: (directory: string) => unknown): NativeShortLineage {
  if (parent === undefined) {
    return { schemaVersion: 1, clipId: randomUUID().replaceAll("-", ""), generation: 0, parent: null };
  }
  const directory = path.resolve(parent), manifestFile = path.join(directory, "PROJECT-MANIFEST.json");
  if (realpathSync(directory) !== directory) throw new Error("Native parent project path must be canonical");
  const bytes = readFileSync(manifestFile), manifestSha256 = createHash("sha256").update(bytes).digest("hex");
  readParent(directory);
  const manifest = JSON.parse(bytes.toString("utf8")) as { projectHash?: unknown; lineage?: unknown };
  if (createHash("sha256").update(readFileSync(manifestFile)).digest("hex") !== manifestSha256) {
    throw new Error("Native parent manifest changed while its lineage was recorded");
  }
  if (manifest.lineage === undefined) {
    throw new Error("Native parent has no clip lineage; build a new root without --parent");
  }
  const prior = assertNativeShortLineage(manifest.lineage);
  if (prior.generation >= MAX_LINEAGE_GENERATION || typeof manifest.projectHash !== "string" || !SHA.test(manifest.projectHash)) {
    throw new Error("Native parent lineage is exhausted or its project hash is invalid");
  }
  return { schemaVersion: 1, clipId: prior.clipId, generation: prior.generation + 1,
    parent: { path: directory, projectHash: manifest.projectHash, manifestSha256, clipId: prior.clipId,
      generation: prior.generation } };
}
