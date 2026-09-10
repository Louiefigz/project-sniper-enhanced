import {
  mkdirSync,
  renameSync,
  rmSync,
} from "fs";
import { lstat, mkdir, readdir } from "fs/promises";
import { randomUUID } from "crypto";
import path from "path";
import {
  createProjectRoot,
  findProjectRoot,
  readProjectJson,
  recordProjectIntentResolution,
  writeProjectJson,
} from "../../_lib/workspace";
import { upsertProject } from "../../_lib/projects-registry";
import type { IntentCapabilityResolution } from "@/lib/producer/intent-capabilities";
import type { ProjectIntent } from "@/lib/producer/intent-presets";
import {
  copyStableSource,
  stableCopySource,
  type StableCopySource,
} from "./source-copy";

// WORKSPACE TARGET RESOLUTION for the ingest route. Default (no outDir, no
// projectRoot): create a NEW workspace project — footage ≤2GB is COPIED into
// <project>/source/ so manifest paths point at the copy; larger footage stays
// referenced in place (project.json records sourceMode:"referenced"). The
// manifest lands in <project>/source/ (the "ingested" stage marker); renders
// land in <project>/producer/.

const COPY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024; // 2GB

export interface IngestTarget {
  ingestInput: string; // what ingest.py reads (the source copy when copied)
  manifestDir: string; // where asset_manifest.json + transcripts land
  outDir: string; // the render out dir handed to the UI (producer/)
  projectRoot: string | null; // null = legacy explicit outDir outside a project
  fresh: boolean; // only a fresh target receives a managed source copy
}

export interface SourceCopyProgress {
  copiedBytes: number;
  totalBytes: number;
  currentFile: string;
}

export interface PreparedIngestTarget {
  target: IngestTarget;
  placement: "existing" | "copied" | "referenced";
  totalBytes: number;
}

interface ScanState {
  entries: StableCopySource[];
  totalBytes: number;
  tooLarge: boolean;
}

function abortIfNeeded(signal: AbortSignal): void {
  if (signal.aborted) throw new DOMException("Source placement canceled", "AbortError");
}

async function scanDirectory(
  dir: string,
  base: string,
  state: ScanState,
  signal: AbortSignal,
): Promise<void> {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    abortIfNeeded(signal);
    if (state.tooLarge) return;
    const absolute = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      await scanDirectory(absolute, base, state, signal);
      continue;
    }
    if (!entry.isFile()) throw new Error(`Source folders cannot contain symbolic links: ${absolute}`);
    const info = await lstat(absolute, { bigint: true });
    if (!info.isFile() || info.isSymbolicLink()) {
      throw new Error(`Source file changed while scanning: ${absolute}`);
    }
    const size = Number(info.size);
    state.entries.push(
      stableCopySource(absolute, path.relative(base, absolute), info),
    );
    state.totalBytes += size;
    state.tooLarge = state.totalBytes > COPY_LIMIT_BYTES;
  }
}

async function scanSource(inputPath: string, signal: AbortSignal): Promise<{
  entries: StableCopySource[];
  totalBytes: number;
  directory: boolean;
  tooLarge: boolean;
}> {
  abortIfNeeded(signal);
  const stat = await lstat(inputPath, { bigint: true });
  if (stat.isFile()) {
    const size = Number(stat.size);
    return {
      entries: [stableCopySource(inputPath, path.basename(inputPath), stat)],
      totalBytes: size,
      directory: false,
      tooLarge: size > COPY_LIMIT_BYTES,
    };
  }
  if (!stat.isDirectory()) throw new Error(`Unsupported source type: ${inputPath}`);
  const state: ScanState = { entries: [], totalBytes: 0, tooLarge: false };
  await scanDirectory(inputPath, inputPath, state, signal);
  return { ...state, directory: true };
}

function initializeFreshProject(target: IngestTarget, referenced: boolean): void {
  if (!target.projectRoot) throw new Error("Fresh ingest target has no project root");
  mkdirSync(target.manifestDir, { recursive: true });
  mkdirSync(target.outDir, { recursive: true });
  writeProjectJson(target.projectRoot, {
    origin: "raw",
    history: [],
    ...(referenced ? { sourceMode: "referenced" as const } : {}),
  });
}

/** Place a fresh source asynchronously after the response stream and writer lease exist. */
export async function prepareIngestTarget(
  target: IngestTarget,
  onProgress: (progress: SourceCopyProgress) => void,
  signal: AbortSignal,
): Promise<PreparedIngestTarget> {
  if (!target.fresh) {
    mkdirSync(target.manifestDir, { recursive: true });
    mkdirSync(target.outDir, { recursive: true });
    return { target, placement: "existing", totalBytes: 0 };
  }
  const scan = await scanSource(target.ingestInput, signal);
  if (scan.tooLarge) {
    initializeFreshProject(target, true);
    return { target, placement: "referenced", totalBytes: scan.totalBytes };
  }
  const root = target.projectRoot as string;
  const staging = path.join(root, `.source-copy-${randomUUID()}`);
  let copiedBytes = 0;
  try {
    await mkdir(staging, { recursive: false });
    for (const entry of scan.entries) {
      await copyStableSource(
        entry, path.join(staging, entry.relative), (bytes) => {
          copiedBytes += bytes;
          onProgress({
            copiedBytes,
            totalBytes: scan.totalBytes,
            currentFile: entry.relative,
          });
        }, signal,
      );
    }
    abortIfNeeded(signal);
    renameSync(staging, target.manifestDir);
  } catch (error) {
    rmSync(staging, { recursive: true, force: true });
    throw error;
  }
  initializeFreshProject(target, false);
  const placed = {
    ...target,
    ingestInput: scan.directory
      ? target.manifestDir
      : path.join(target.manifestDir, path.basename(target.ingestInput)),
  };
  return { target: placed, placement: "copied", totalBytes: scan.totalBytes };
}

/** Remove only the fresh project shell owned by a failed/cancelled ingest. */
export function discardFreshIngestTarget(target: IngestTarget): void {
  if (target.fresh && target.projectRoot) rmSync(target.projectRoot, { recursive: true, force: true });
}

/** Create a fresh workspace project for raw footage and aim ingest at it. */
function newProjectTarget(inputPath: string): IngestTarget {
  const root = createProjectRoot(path.basename(inputPath));
  const outDir = path.join(root, "producer");
  return {
    ingestInput: inputPath,
    manifestDir: path.join(root, "source"),
    outDir,
    projectRoot: root,
    fresh: true,
  };
}

/** Ingest into an EXISTING project (segment "Ingest → edit"): origin preserved. */
function existingProjectTarget(inputPath: string, projectRoot: string): IngestTarget {
  const clean = projectRoot.replace(/\/$/, "");
  if (!readProjectJson(clean)) {
    throw new Error(`projectRoot has no project.json: ${clean}`);
  }
  const manifestDir = path.join(clean, "source");
  const outDir = path.join(clean, "producer");
  return { ingestInput: inputPath, manifestDir, outDir, projectRoot: clean, fresh: false };
}

/**
 * Resolve where this ingest reads from and writes to. An explicit outDir keeps
 * the pre-workspace behavior exactly (manifest + renders in outDir).
 */
export function resolveIngestTarget(
  inputPath: string,
  outDir?: string,
  projectRoot?: string,
): IngestTarget {
  if (outDir) {
    return {
      ingestInput: inputPath,
      manifestDir: outDir,
      outDir,
      projectRoot: findProjectRoot(outDir),
      fresh: false,
    };
  }
  if (projectRoot) return existingProjectTarget(inputPath, projectRoot);
  return newProjectTarget(inputPath);
}

/** Request to reconcile: fresh input first, otherwise the project's preserved request. */
export function requestedIngestIntent(
  target: IngestTarget,
  intent?: ProjectIntent,
): ProjectIntent | undefined {
  if (intent) return intent;
  if (!target.projectRoot) return undefined;
  const project = readProjectJson(target.projectRoot);
  return project?.requestedIntent ?? project?.resolvedIntent ?? project?.intent;
}

/** Post-success provenance; persist requested/effective capability authority. */
export function recordIngested(
  target: IngestTarget,
  resolution?: IntentCapabilityResolution,
): ProjectIntent | undefined {
  if (!target.projectRoot) return resolution?.resolvedIntent;
  const project = readProjectJson(target.projectRoot);
  if (project) {
    if (resolution) recordProjectIntentResolution(target.projectRoot, resolution, "ingested");
    else {
      writeProjectJson(target.projectRoot, {
        ...project,
        history: [...project.history, { stage: "ingested", at: new Date().toISOString() }],
      });
    }
  }
  upsertProject(target.outDir, path.basename(target.projectRoot));
  return resolution?.resolvedIntent ?? project?.resolvedIntent ?? project?.intent;
}
