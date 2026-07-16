import { createHash, randomUUID } from "node:crypto";
import {
  appendFileSync,
  existsSync,
  readFileSync,
  rmSync,
} from "node:fs";
import path from "node:path";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { retainedClaudeSessionId } from "../auto-edit/authoring-session";

export type LiveBuildStatus = "running" | "interrupted" | "failed" | "qc_failed" | "complete";

export interface LiveBuildQcFailure {
  lens?: string;
  materialIssues: Record<string, unknown>[];
  evidencePaths: string[];
  candidateFingerprint: string;
  message: string;
  failedAt: string;
}

export interface LiveBuildState {
  schemaVersion: 1;
  runId: string;
  sessionId: string;
  sessionEstablished: boolean;
  planHash: string;
  doctrineHash: string;
  projectId: string;
  projectPath: string;
  parentTimelineId: string;
  parentFingerprint: string;
  candidateTimelineId: string;
  latestFingerprint: string;
  status: LiveBuildStatus;
  operationsSeen: number;
  operationsCompleted: number;
  startedAt: string;
  updatedAt: string;
  error?: string;
  qcFailure?: LiveBuildQcFailure;
}

export interface NewLiveBuildState {
  dir: string;
  planHash: string;
  doctrineHash: string;
  projectId: string;
  projectPath: string;
  parentTimelineId: string;
  parentFingerprint: string;
  candidateTimelineId: string;
  candidateFingerprint: string;
  priorSessionId?: string;
}

export function liveBuildStatePath(dir: string): string {
  return path.join(dir, ".palmier-live-build.state.json");
}

export function liveBuildJournalPath(dir: string): string {
  return path.join(dir, ".palmier-live-build.jsonl");
}

function validState(value: unknown): value is LiveBuildState {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Partial<LiveBuildState>;
  return row.schemaVersion === 1
    && typeof row.runId === "string"
    && typeof row.sessionId === "string"
    && typeof row.planHash === "string"
    && typeof row.projectId === "string"
    && typeof row.parentTimelineId === "string"
    && typeof row.candidateTimelineId === "string"
    && ["running", "interrupted", "failed", "qc_failed", "complete"].includes(String(row.status));
}

export function assertLiveBuildRequest(
  input: Pick<NewLiveBuildState, "dir" | "planHash" | "doctrineHash" | "projectId"
    | "projectPath" | "parentTimelineId" | "parentFingerprint">,
  resume: boolean,
): LiveBuildState | null {
  const current = readLiveBuildState(input.dir);
  if (!current && resume) throw new Error("No retained Palmier live build is available to resume.");
  if (!current) return null;
  const sameParent = current.planHash === input.planHash
    && current.doctrineHash === input.doctrineHash
    && current.projectId === input.projectId
    && current.projectPath === input.projectPath
    && current.parentTimelineId === input.parentTimelineId
    && current.parentFingerprint === input.parentFingerprint;
  if (!sameParent && resume) {
    throw new Error("The retained Palmier live build belongs to different approved authority.");
  }
  if (!resume && sameParent) {
    const action = current.status === "complete" ? "already completed" : "must be resumed";
    throw new Error(`The retained live build ${action}; refusing to fork another candidate.`);
  }
  return current;
}

export function readLiveBuildState(dir: string): LiveBuildState | null {
  const filePath = liveBuildStatePath(dir);
  if (!existsSync(filePath)) return null;
  try {
    const value: unknown = JSON.parse(readFileSync(filePath, "utf8"));
    if (!validState(value)) throw new Error("invalid live-build state");
    return value;
  } catch (error) {
    throw new Error(`Palmier live-build state is unreadable: ${(error as Error).message}`);
  }
}

function sameAuthority(state: LiveBuildState, input: NewLiveBuildState): boolean {
  return state.planHash === input.planHash
    && state.doctrineHash === input.doctrineHash
    && state.projectId === input.projectId
    && state.projectPath === input.projectPath
    && state.parentTimelineId === input.parentTimelineId
    && state.parentFingerprint === input.parentFingerprint
    && state.candidateTimelineId === input.candidateTimelineId;
}

function resumeState(
  input: NewLiveBuildState,
  current: LiveBuildState | null,
  now: string,
): LiveBuildState {
  if (!current || !sameAuthority(current, input)) {
    throw new Error("No retained Palmier live-build session matches this approved plan and timeline.");
  }
  if (current.status === "complete") {
    throw new Error("This approved plan already completed its retained Palmier live build.");
  }
  return { ...current, status: "running",
    latestFingerprint: input.candidateFingerprint, updatedAt: now,
    error: undefined };
}

function createState(
  input: NewLiveBuildState,
  sessionId: string,
  now: string,
): LiveBuildState {
  return {
    schemaVersion: 1, runId: randomUUID(), sessionId,
    sessionEstablished: input.priorSessionId === sessionId,
    planHash: input.planHash, doctrineHash: input.doctrineHash,
    projectId: input.projectId, projectPath: input.projectPath,
    parentTimelineId: input.parentTimelineId,
    parentFingerprint: input.parentFingerprint,
    candidateTimelineId: input.candidateTimelineId,
    latestFingerprint: input.candidateFingerprint, status: "running",
    operationsSeen: 0, operationsCompleted: 0,
    startedAt: now, updatedAt: now,
  };
}

export function prepareLiveBuildState(
  input: NewLiveBuildState,
  resume: boolean,
): LiveBuildState {
  const current = readLiveBuildState(input.dir);
  const now = new Date().toISOString();
  if (resume) {
    const resumed = resumeState(input, current, now);
    writeLiveBuildState(input.dir, resumed);
    return resumed;
  }
  if (current && sameAuthority(current, input)) {
    const action = current.status === "complete" ? "already completed" : "must be resumed";
    throw new Error(`The retained live build ${action}; refusing to replay the approved plan.`);
  }
  const sessionId = retainedClaudeSessionId(input.priorSessionId);
  rmSync(liveBuildJournalPath(input.dir), { force: true });
  const created = createState(input, sessionId, now);
  writeLiveBuildState(input.dir, created);
  return created;
}

export function writeLiveBuildState(dir: string, state: LiveBuildState): void {
  atomicWriteJsonSync(liveBuildStatePath(dir), state);
}

export function patchLiveBuildState(
  dir: string,
  patch: Partial<LiveBuildState>,
): LiveBuildState {
  const current = readLiveBuildState(dir);
  if (!current) throw new Error("Palmier live-build state disappeared");
  const next = { ...current, ...patch, updatedAt: new Date().toISOString() };
  writeLiveBuildState(dir, next);
  return next;
}

export function appendLiveBuildJournal(
  dir: string,
  value: Record<string, unknown>,
): void {
  const row: Record<string, unknown> = { at: new Date().toISOString(), ...value };
  const serialized = JSON.stringify(row);
  const bounded = Buffer.byteLength(serialized) <= 16_000 ? serialized : JSON.stringify({
    at: row["at"],
    event: row["event"],
    operationId: row["operationId"],
    tool: row["tool"],
    lane: row["lane"],
    summary: row["summary"],
    status: row["status"],
    elapsedMs: row["elapsedMs"],
    payloadHash: createHash("sha256").update(serialized).digest("hex"),
    truncated: true,
  });
  appendFileSync(liveBuildJournalPath(dir), `${bounded}\n`, {
    encoding: "utf8", mode: 0o600,
  });
}

export function readLiveBuildJournal(dir: string, limit = 100): Record<string, unknown>[] {
  const filePath = liveBuildJournalPath(dir);
  if (!existsSync(filePath)) return [];
  return readFileSync(filePath, "utf8").trim().split("\n").filter(Boolean)
    .slice(-limit).flatMap((line) => {
      try {
        const value: unknown = JSON.parse(line);
        return value && typeof value === "object" && !Array.isArray(value)
          ? [value as Record<string, unknown>] : [];
      } catch { return []; }
    });
}
