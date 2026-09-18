import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { canonicalProducerDir } from "../../_lib/workspace";
import { StudioError } from "./model";

const MAX_FILES = 3_000;
const MAX_JSON_BYTES = 4 * 1024 * 1024;

/** Apply the shared workspace policy and reject ambiguous request spellings. */
export function studioProducerDir(value: unknown): string {
  if (typeof value !== "string" || value.length > 2_048
      || value.includes("\\") || value.split("/").includes("..")) {
    throw new StudioError("dir must be a canonical Producer path", 400, "INVALID_PROJECT");
  }
  try { return canonicalProducerDir(value); } catch (error) {
    throw new StudioError((error as Error).message, 400, "INVALID_PROJECT");
  }
}

function regularPath(file: string): boolean {
  if (!fs.existsSync(file)) {
    if (fs.lstatSync(file, { throwIfNoEntry: false })) {
      throw new StudioError("Broken symlinks are not supported in Studio projects");
    }
    return false;
  }
  const stat = fs.lstatSync(file);
  if (stat.isSymbolicLink() || (!stat.isFile() && !stat.isDirectory())) {
    throw new StudioError("Studio inputs and projection must not contain symlinks or special files");
  }
  return true;
}

/** Refuse symlink traversal before Python reads or writes the generated view. */
export function assertStudioPaths(dir: string): void {
  readStudioJson(path.join(path.dirname(dir), "project.json"));
  for (const name of ["edit_plan.json", "base_final.mp4", "base.fingerprint.json", "base_plan.json"]) {
    const file = path.join(dir, name);
    if (regularPath(file) && !fs.statSync(file).isFile()) {
      throw new StudioError("Studio inputs must be regular files");
    }
    if (name.endsWith(".json")) readStudioJson(file);
  }
  const studio = path.join(dir, "studio");
  if (!regularPath(studio)) return;
  const pending = [studio];
  let count = 0;
  while (pending.length) {
    const current = pending.pop()!;
    if (++count > MAX_FILES) throw new StudioError("Studio projection exceeds the bounded file limit");
    regularPath(current);
    if (fs.statSync(current).isDirectory()) {
      pending.push(...fs.readdirSync(current).map((name) => path.join(current, name)));
    }
  }
  assertManifestPaths(dir);
}

export function readStudioJson(file: string): Record<string, unknown> | null {
  if (!regularPath(file)) return null;
  if (!fs.statSync(file).isFile() || fs.statSync(file).size > MAX_JSON_BYTES) {
    throw new StudioError("Studio metadata is not a bounded regular JSON file");
  }
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    return value;
  } catch { throw new StudioError("Studio metadata is malformed; no files were discarded"); }
}

function safeRelative(value: unknown): value is string {
  return typeof value === "string" && value.length > 0
    && !path.isAbsolute(value) && !value.includes("\\")
    && !value.split("/").some((part) => part === ".." || part === "." || !part);
}

function assertManifestPaths(dir: string): void {
  const manifest = readStudioJson(path.join(dir, "studio", "studio.manifest.json"));
  if (!manifest) return;
  const media = manifest.media as { target?: unknown; rel?: unknown } | undefined;
  if (media?.target !== path.join(dir, "base_final.mp4") || !safeRelative(media?.rel)) {
    throw new StudioError("Studio manifest does not bind to this project's base video");
  }
  const files = manifest.files;
  if (!files || typeof files !== "object" || Array.isArray(files)
      || Object.keys(files).some((name) => !safeRelative(name))) {
    throw new StudioError("Studio manifest contains invalid tracked paths");
  }
}

async function mediaHash(file: string): Promise<string> {
  if (fs.statSync(file).size > 8 * 1024 ** 3) {
    throw new StudioError("Studio base exceeds the 8 GiB interactive-open limit");
  }
  const hash = createHash("sha256");
  const stream = fs.createReadStream(file, { signal: AbortSignal.timeout(20_000) });
  for await (const chunk of stream) hash.update(chunk);
  return hash.digest("hex");
}

/** Verify actual copied media bytes, not just the legacy size-only manifest. */
export async function verifyStudioMedia(dir: string, verifyCopy = true): Promise<string> {
  const base = path.join(dir, "base_final.mp4");
  const digest = await mediaHash(base);
  const manifest = readStudioJson(path.join(dir, "studio", "studio.manifest.json"));
  if (manifest && verifyCopy) {
    const relative = (manifest.media as { rel: string }).rel;
    if (await mediaHash(path.join(dir, "studio", relative)) !== digest) {
      throw new StudioError("Studio base copy differs from current footage; projection was preserved");
    }
  }
  return digest;
}
