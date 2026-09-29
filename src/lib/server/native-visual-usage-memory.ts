import { existsSync, lstatSync, opendirSync, realpathSync } from "node:fs";
import path from "node:path";
import { NATIVE_USAGE_DIRECTORY } from "./native-visual-usage-receipt";
import { readNativeVisualUsageReceipt } from "./native-visual-usage-reader";
import type { VisualUsageProject } from "./visual-plan-related-use";

const MAX_RECEIPT_READS = 128;
const MAX_USAGE_PROJECTS = 8;
const CURRENT_NAME = /^(\d{13})-(short|long)-([a-f0-9]{64})\.json$/u;
const LEGACY_NAME = /^([a-f0-9]{64})\.json$/u;

interface Candidate { file: string; order: string; producerDir: string }

function candidate(directory: string, name: string, mode: "short" | "long"): Candidate | null {
  const producerDir = path.dirname(directory);
  const current = CURRENT_NAME.exec(name);
  if (current) {
    return current[2] === mode
      ? { file: path.join(directory, name), order: name, producerDir } : null;
  }
  return LEGACY_NAME.test(name)
    ? { file: path.join(directory, name), order: `0000000000000-${mode}-${name}`,
      producerDir } : null;
}

function retainNewest(rows: Candidate[], row: Candidate): void {
  rows.push(row);
  rows.sort((left, right) => right.order.localeCompare(left.order));
  if (rows.length > MAX_RECEIPT_READS) rows.pop();
}

function receiptCandidates(projectDir: string, mode: "short" | "long"): Candidate[] {
  const producerDir = path.join(projectDir, "producer");
  const directory = path.join(producerDir, NATIVE_USAGE_DIRECTORY);
  if (!existsSync(directory)) return [];
  if (lstatSync(directory).isSymbolicLink() || !lstatSync(directory).isDirectory()
      || realpathSync(directory) !== directory) return [];
  const rows: Candidate[] = [], handle = opendirSync(directory);
  try {
    for (;;) {
      const entry = handle.readSync();
      if (!entry) break;
      const row = entry.isFile() && !entry.isSymbolicLink()
        ? candidate(directory, entry.name, mode) : null;
      if (row) retainNewest(rows, row);
    }
  } finally {
    handle.closeSync();
  }
  return rows;
}

/** Revalidate at most 128 globally newest receipt candidates and return eight uses. */
export function nativeVisualUsageProjectsAcross(
  projectDirs: string[],
  mode: "short" | "long",
): VisualUsageProject[] {
  const candidates: Candidate[] = [];
  for (const projectDir of projectDirs) {
    for (const row of receiptCandidates(projectDir, mode)) retainNewest(candidates, row);
  }
  const rows = candidates.flatMap(({ file, producerDir }) => {
    try {
      const project = readNativeVisualUsageReceipt(file, producerDir);
      return project.projectId.startsWith(`native-${mode}-`) ? [project] : [];
    } catch {
      return [];
    }
  });
  const unique = new Map<string, VisualUsageProject>();
  for (const row of rows.sort((left, right) => right.approvedAt.localeCompare(left.approvedAt)
      || left.projectId.localeCompare(right.projectId))) {
    const identity = `${row.planSha256}:${row.applicationSha256}`;
    if (!unique.has(identity)) unique.set(identity, row);
  }
  return [...unique.values()].slice(0, MAX_USAGE_PROJECTS);
}

/** Read the newest bounded set of immutable current native usage receipts. */
export function nativeVisualUsageProjects(
  projectDir: string,
  mode: "short" | "long",
): VisualUsageProject[] {
  return nativeVisualUsageProjectsAcross([projectDir], mode);
}
