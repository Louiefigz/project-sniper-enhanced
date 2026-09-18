import { lstatSync, readFileSync } from "node:fs";
import path from "node:path";
import {
  guardPalmierCanonicalForAiEdit,
  PalmierCanonicalError,
} from "../ai-edit/palmier-canonical";
import { classifyPalmierWorkspace } from "../ai-edit/palmier-workspace-classification";

type RecordValue = Record<string, unknown>;

const RECOVERY = "Keep this project's Palmier workflow, or explicitly create a separate "
  + "Sniper branch from a known approved source/cut. No in-place MP4 migration was started.";

function conflict(detail: string): PalmierCanonicalError {
  return new PalmierCanonicalError(`${detail} ${RECOVERY}`, 409);
}

function object(value: unknown): RecordValue | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue : null;
}

/** Missing is different from unsafe, corrupt, or unreadable ownership evidence. */
function readRecord(dir: string, name: string): RecordValue | null {
  try {
    const file = path.join(dir, name);
    const stat = lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1) {
      throw conflict(`${name} is not one safe regular authority file.`);
    }
    const row = object(JSON.parse(readFileSync(file, "utf8")) as unknown);
    if (!row) throw conflict(`${name} is not an authority object.`);
    return row;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    if (error instanceof PalmierCanonicalError) throw error;
    throw conflict(`Cannot verify ${name}: ${(error as Error).message}`);
  }
}

function assertBootstrap(state: RecordValue, authority: RecordValue | null): void {
  const draft = object(state.draft);
  const coverage = object(authority?.readbackCoverage);
  const eligible = state.ownership === "sniper" && state.workspaceMode === "managed-draft"
    && (draft?.assetKind === "source" || draft?.assetKind === "saved-cut")
    && draft.authoritative === false && state.workingCheckpoint === undefined
    && authority?.schemaVersion === 1 && authority.authority === "palmier"
    && authority.origin === "sniper-bootstrap" && coverage?.complete === true
    && authority.projectId === state.projectId && authority.timelineId === state.latestTimelineId
    && typeof authority.fingerprint === "string" && /^[a-f0-9]{64}$/.test(authority.fingerprint);
  if (!eligible) {
    throw conflict("This project has edited, promoted, handed-off, or unproved Palmier authority.");
  }
}

/** Protect old Palmier heads before any plan refit, journal, or MP4 writer starts.
 *
 * New projects do not contact Palmier. An old non-authoritative source/cut
 * bootstrap is the only exception: the existing bounded guard must reobserve
 * it unchanged. That readback never opens, edits, or exports the app; detected
 * drift may be recorded locally to preserve the human revision. Offline labels
 * alone cannot prove no human has edited since the bootstrap was captured.
 */
export async function guardMp4LaunchAuthority(
  dir: string,
  reobserve: (dir: string) => Promise<void> = guardPalmierCanonicalForAiEdit,
): Promise<void> {
  const state = readRecord(dir, "palmier.sync.json");
  const authority = readRecord(dir, "palmier.timeline-authority.json");
  const candidate = readRecord(dir, "palmier.timeline-candidate.json");
  if (!state && !authority && !candidate) return;
  if (!state || candidate) {
    throw conflict("Palmier authority is orphaned or includes a separate candidate revision.");
  }
  const workspace = classifyPalmierWorkspace(dir);
  if (workspace.state !== "managed") {
    throw conflict(workspace.state === "invalid" ? workspace.error
      : "Palmier workspace authority disappeared before launch.");
  }
  assertBootstrap(state, authority);
  try {
    await reobserve(dir);
  } catch (error) {
    throw conflict(`The existing Palmier bootstrap could not be proved unchanged: ${(error as Error).message}`);
  }
}
