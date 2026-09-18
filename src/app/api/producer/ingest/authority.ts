/** Bind every existing ingest destination to its physical project and checkpoint. */
import { existsSync, lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { readCutPreviewObject } from "../auto-edit/cut-preview-receipt";
import type { IngestRequest } from "./request";

export interface MutationAuthority { root: string; producerDir: string }

/** Missing leaf directories are allowed only beneath unchanged canonical directories. */
function canonicalDirectory(directory: string): void {
  let current = directory;
  while (!existsSync(current)) {
    // A dangling symlink is still a supplied path, not an absent directory.
    if (present(current)) throw new Error("Ingest destination contains a dangling link");
    const parent = path.dirname(current);
    if (parent === current) throw new Error("Ingest destination has no existing parent");
    current = parent;
  }
  if (!lstatSync(current).isDirectory() || realpathSync(current) !== current) {
    throw new Error("Ingest destination must use canonical directories without symbolic links");
  }
}

function selectedDirectory(value: string): string {
  const clean = value.replace(/\/$/, "");
  if (!path.isAbsolute(clean) || path.normalize(clean) !== clean || clean === path.parse(clean).root
      || clean.length > 4096 || /[\0\r\n\\]/u.test(clean)) throw new Error("Ingest target must be a canonical absolute directory");
  canonicalDirectory(clean);
  return clean;
}

function present(file: string): boolean {
  try { lstatSync(file); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}

function containingProject(directory: string): string | null {
  const roots = new Set<string>();
  for (let current = directory; current !== path.dirname(current); current = path.dirname(current)) {
    const managed = present(path.join(current, "project.json"));
    const oldLayout = present(path.join(current, "producer")) && present(path.join(current, "source"));
    if (managed) {
      const marker = readCutPreviewObject(path.join(current, "project.json")).value;
      if (!marker || Array.isArray(marker) || typeof marker.origin !== "string") throw new Error("Ingest project marker is malformed");
    }
    if (managed || oldLayout) roots.add(current);
  }
  if (roots.size > 1) throw new Error("Ingest target has ambiguous nested project ownership");
  return roots.values().next().value ?? null;
}

/** Explicit output directories inside projects share the real producer checkpoint. */
export function existingIngestAuthority(request: Pick<IngestRequest, "projectRoot" | "outDir">): MutationAuthority | null {
  if (request.projectRoot !== undefined && request.outDir !== undefined) throw new Error("Choose projectRoot or outDir, not both");
  const value = request.projectRoot ?? request.outDir;
  if (value === undefined) return null;
  const directory = selectedDirectory(value), root = containingProject(directory);
  if (request.projectRoot !== undefined && (root !== directory || !existsSync(path.join(directory, "project.json")))) {
    throw new Error("projectRoot must name the owning project.json directory");
  }
  if (!root) return { root: directory, producerDir: directory };
  const source = path.join(root, "source"), producerDir = path.join(root, "producer");
  if (![root, source, producerDir].includes(directory)) throw new Error("Nested project ingest destinations are unsupported; use projectRoot or its source/producer directory");
  canonicalDirectory(root); canonicalDirectory(source); canonicalDirectory(producerDir);
  return { root, producerDir };
}

/** Folder ingest writes a B-roll catalog; a file-only import remains read-only. */
export function assertIngestInputAuthority(request: Pick<IngestRequest, "inputPath" | "projectRoot" | "outDir">): void {
  const physicalInput = realpathSync(request.inputPath);
  if (!lstatSync(physicalInput).isDirectory()) return;
  const inputOwner = containingProject(physicalInput);
  if (!inputOwner) return;
  const target = existingIngestAuthority(request);
  if (!target || target.root !== inputOwner) {
    throw new Error("Directory ingest cannot update another project's supporting-media catalog; select a media file or the owning project");
  }
}

/** A reclassified path cannot silently change the owner of an already held lease. */
export function assertSameIngestAuthority(current: MutationAuthority | null, held: MutationAuthority): void {
  if (!current || current.root !== held.root || current.producerDir !== held.producerDir) {
    throw new Error("Ingest destination ownership changed while the project lease was held");
  }
}
