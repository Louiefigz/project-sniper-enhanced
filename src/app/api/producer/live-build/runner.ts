import path from "node:path";
import { buildLiveBuildArgs } from "./args";
import {
  captureLiveBuildQcAuthority,
  type TimelineIdentity,
} from "./authority";
import {
  checkpointLiveBuildCandidate,
  observeLiveBuildCandidate,
} from "./candidate";
import {
  prepareLiveBuildCandidateRuntime,
  sameLiveBuildTimelineIdentity,
} from "./candidate-runtime";
import {
  appendLiveBuildHead,
  appendLiveBuildOperationEvent,
  latestLiveBuildHead,
  liveBuildJournalCounts,
  operationsAfterHead,
  pendingMutationIds,
  type LiveBuildJournalLedger,
} from "./journal";
import type { LiveBuildPreflight } from "./preflight";
import { buildLiveBuildPrompt } from "./prompt";
import { runLiveBuildProcess } from "./process";
import {
  pauseLiveBuildNoDelta,
  pauseLiveBuildRuntimeViolation,
} from "./reconciliation";
import {
  patchLiveBuildState,
  readLiveBuildState,
  type LiveBuildState,
} from "./state";
import type { LiveBuildProcessResult } from "./process";
import { runLiveBuildCandidateQc } from "../palmier/candidate-qc/runner";
import type { PalmierOpEvent } from "@/lib/producer/palmier-op-event";

type Send = (event: Record<string, unknown>) => void;

function readDirs(input: LiveBuildPreflight): string[] {
  return [...new Set([
    input.dir,
    path.dirname(input.planPath),
    path.dirname(input.manifestPath),
    ...Object.values(input.doctrineFiles).map(path.dirname),
  ])];
}

interface PreparedRuntime {
  preflight: LiveBuildPreflight;
  parent: TimelineIdentity;
  candidate: TimelineIdentity;
  state: LiveBuildState;
  ledger: LiveBuildJournalLedger;
  sessionRecorded: boolean;
  args: string[];
}

interface ExecutedRuntime {
  process: LiveBuildProcessResult;
  operationCount: number;
  candidate: TimelineIdentity;
}

interface ClosedOperationJournal {
  operationCount: number;
  candidate: TimelineIdentity;
}

export function recordLiveBuildOperation(
  dir: string,
  state: LiveBuildState,
  event: PalmierOpEvent,
  ledger: LiveBuildJournalLedger,
): LiveBuildState {
  appendLiveBuildOperationEvent(dir, ledger, event);
  return patchLiveBuildState(dir, liveBuildJournalCounts(ledger));
}

async function prepareRuntime(
  preflight: LiveBuildPreflight,
  resume: boolean,
  send: Send,
  signal?: AbortSignal,
): Promise<PreparedRuntime> {
  send({ event: "live_build_progress", step: "candidate",
    message: resume ? "Restoring the retained editable candidate." : "Forking the verified parent into a visible editable candidate." });
  const prepared = await prepareLiveBuildCandidateRuntime(
    preflight, resume, signal);
  const execution = { ...preflight, timelineId: prepared.candidate.timelineId,
    timelineFingerprint: prepared.candidate.fingerprint };
  const prompt = buildLiveBuildPrompt(
    execution, resume, prepared.state.resumeAuthority);
  const { state } = prepared;
  const args = buildLiveBuildArgs({ prompt, sessionId: state.sessionId,
    resume: state.sessionEstablished, readDirs: readDirs(preflight) });
  send({ event: "live_build_started", runId: state.runId,
    sessionId: state.sessionId, timelineId: prepared.candidate.timelineId,
    message: "Claude is applying the approved plan directly to the visible Palmier candidate." });
  return { preflight, ...prepared,
    sessionRecorded: state.sessionEstablished, args };
}

function processCallbacks(runtime: PreparedRuntime, send: Send) {
  return {
    onSession: () => {
      if (runtime.sessionRecorded) return;
      runtime.sessionRecorded = true;
      runtime.state = patchLiveBuildState(runtime.preflight.dir, {
        sessionEstablished: true,
      });
    },
    onEvent: (event: PalmierOpEvent) => {
      try {
        runtime.state = recordLiveBuildOperation(
          runtime.preflight.dir, runtime.state, event, runtime.ledger,
        );
      } catch (error) {
        pauseLiveBuildRuntimeViolation(
          runtime.preflight.dir, runtime.state, error, [event.operationId]);
      }
      send({ ...event });
    },
  };
}

function emitLatency(result: LiveBuildProcessResult, send: Send): void {
  send({ event: "live_build_latency", firstMutationMs: result.firstMutationMs,
    executionMs: result.elapsedMs,
    status: result.firstMutationMs <= 45_000 ? "pass" : "warning",
    message: result.firstMutationMs <= 45_000
      ? "First editable Palmier mutation landed within the live-build target."
      : "First editable mutation exceeded the 45-second target; evidence is preserved for profiling." });
}

function qcFailure(error: Error, runtime: PreparedRuntime) {
  const value = error as Error & {
    candidateQcFailure?: {
      lens?: string;
      materialIssues?: Record<string, unknown>[];
    };
    candidateQcEvidencePaths?: string[];
  };
  return {
    lens: value.candidateQcFailure?.lens,
    materialIssues: value.candidateQcFailure?.materialIssues ?? [],
    evidencePaths: value.candidateQcEvidencePaths ?? [],
    candidateFingerprint: runtime.state.latestFingerprint,
    message: error.message,
    failedAt: new Date().toISOString(),
  };
}

async function closeOperationJournal(
  runtime: PreparedRuntime,
  result: LiveBuildProcessResult,
  signal?: AbortSignal,
): Promise<ClosedOperationJournal> {
  const counts = liveBuildJournalCounts(runtime.ledger);
  if (pendingMutationIds(runtime.ledger).length
      || result.operationsSeen !== result.operationsCompleted) {
    throw new Error(
      "Palmier live build ended with an unresolved mutation lifecycle.");
  }
  const observed = await observeLiveBuildCandidate(runtime.preflight, signal);
  if (!sameLiveBuildTimelineIdentity(observed.parent, runtime.parent)
      || observed.candidate.projectId !== runtime.candidate.projectId
      || observed.candidate.timelineId !== runtime.candidate.timelineId) {
    throw new Error(
      "Palmier live-build candidate identity changed before journal closure.");
  }
  const head = latestLiveBuildHead(runtime.ledger);
  if (!head) throw new Error("Palmier live-build journal has no initial head.");
  const applied = operationsAfterHead(runtime.ledger)
    .filter((operation) => operation.status === "applied");
  if (applied.length
      && observed.candidate.fingerprint === head.fingerprint) {
    pauseLiveBuildNoDelta(
      runtime.preflight.dir, runtime.state,
      observed.candidate.fingerprint,
      applied.map((operation) => operation.operationId));
  }
  appendLiveBuildHead(
    runtime.preflight.dir, runtime.ledger, observed.candidate.fingerprint);
  runtime.state = patchLiveBuildState(runtime.preflight.dir, {
    sessionEstablished: true,
    latestFingerprint: observed.candidate.fingerprint,
  });
  return {
    operationCount: counts.operationsCompleted,
    candidate: observed.candidate,
  };
}

async function executeCandidate(
  runtime: PreparedRuntime,
  send: Send,
  signal?: AbortSignal,
): Promise<ExecutedRuntime> {
  const result = await runLiveBuildProcess({
    args: runtime.args, cwd: process.cwd(), expectedSessionId: runtime.state.sessionId,
    signal, ...processCallbacks(runtime, send),
  });
  const closed = await closeOperationJournal(runtime, result, signal);
  const { operationCount } = closed;
  emitLatency(result, send);
  const capture = captureLiveBuildQcAuthority({ preflight: runtime.preflight,
    parent: runtime.parent, sessionId: runtime.state.sessionId, operationCount,
    candidateFingerprint: closed.candidate.fingerprint });
  const checkpoint = await checkpointLiveBuildCandidate(
    runtime.preflight, capture.authorityPath, signal,
    closed.candidate.fingerprint,
  );
  if (!sameLiveBuildTimelineIdentity(checkpoint.parent, runtime.parent)
      || !sameLiveBuildTimelineIdentity(
        checkpoint.candidate, closed.candidate)) {
    throw new Error(
      "Palmier candidate changed after live-build journal closure.");
  }
  runtime.state = patchLiveBuildState(runtime.preflight.dir, {
    latestFingerprint: checkpoint.candidate.fingerprint,
  });
  send({ event: "live_build_readback", timelineId: checkpoint.candidate.timelineId,
    fingerprint: checkpoint.candidate.fingerprint, operationCount,
    message: "Fresh Palmier readback matches the retained candidate; exact export QC is starting." });
  return { process: result, operationCount, candidate: checkpoint.candidate };
}

async function approveCandidate(
  runtime: PreparedRuntime,
  executed: ExecutedRuntime,
  send: Send,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  await runLiveBuildCandidateQc(runtime.preflight.dir, send, {}, signal);
  patchLiveBuildState(runtime.preflight.dir, { status: "complete",
    latestFingerprint: executed.candidate.fingerprint, qcFailure: undefined });
  return {
      event: "live_build_qc_approved",
      runId: runtime.state.runId,
      timelineId: executed.candidate.timelineId,
      fingerprint: executed.candidate.fingerprint,
      operations: executed.operationCount,
      firstMutationMs: executed.process.firstMutationMs,
      executionMs: executed.process.elapsedMs,
      editable: true,
      promoted: false,
      message: "The exact editable candidate passed deterministic, composition, and editorial QC. Promotion remains an explicit operator action.",
  };
}

export async function runLiveBuild(
  preflight: LiveBuildPreflight,
  resume: boolean,
  send: Send,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const runtime = await prepareRuntime(preflight, resume, send, signal);
  let phase: "build" | "qc" = "build";
  try {
    const executed = await executeCandidate(runtime, send, signal);
    phase = "qc";
    return await approveCandidate(runtime, executed, send, signal);
  } catch (reason) {
    const error = reason instanceof Error ? reason : new Error(String(reason));
    const retained = readLiveBuildState(preflight.dir);
    if (retained?.status !== "reconciliation_required") {
      patchLiveBuildState(preflight.dir, {
        status: phase === "qc" ? "qc_failed" : signal?.aborted ? "interrupted" : "failed",
        error: error.message,
        sessionEstablished: runtime.sessionRecorded,
        ...(phase === "qc" ? { qcFailure: qcFailure(error, runtime) } : {}),
      });
    }
    throw error;
  }
}
