import path from "node:path";
import { buildLiveBuildArgs } from "./args";
import {
  captureLiveBuildQcAuthority,
  type TimelineIdentity,
} from "./authority";
import {
  checkpointLiveBuildCandidate,
  prepareLiveBuildCandidate,
} from "./candidate";
import type { LiveBuildPreflight } from "./preflight";
import { buildLiveBuildPrompt } from "./prompt";
import { isLiveBuildMutationTool, runLiveBuildProcess } from "./process";
import {
  appendLiveBuildJournal,
  assertLiveBuildRequest,
  patchLiveBuildState,
  prepareLiveBuildState,
  type LiveBuildState,
} from "./state";
import type { LiveBuildProcessResult } from "./process";
import { runLiveBuildCandidateQc } from "../palmier/candidate-qc/runner";
import type { PalmierOpEvent } from "@/lib/producer/palmier-op-event";

type Send = (event: Record<string, unknown>) => void;

function sameIdentity(left: TimelineIdentity, right: TimelineIdentity): boolean {
  return left.projectId === right.projectId
    && left.timelineId === right.timelineId
    && left.fingerprint === right.fingerprint;
}

function readDirs(input: LiveBuildPreflight): string[] {
  return [...new Set([
    input.dir,
    path.dirname(input.planPath),
    path.dirname(input.manifestPath),
    ...Object.values(input.doctrineFiles).map(path.dirname),
  ])];
}

function parentIdentity(input: LiveBuildPreflight): TimelineIdentity {
  return { projectId: input.projectId, timelineId: input.timelineId,
    fingerprint: input.timelineFingerprint };
}

interface PreparedRuntime {
  preflight: LiveBuildPreflight;
  parent: TimelineIdentity;
  candidate: TimelineIdentity;
  state: LiveBuildState;
  sessionRecorded: boolean;
  args: string[];
}

interface ExecutedRuntime {
  process: LiveBuildProcessResult;
  operationCount: number;
  candidate: TimelineIdentity;
}

export function recordLiveBuildOperation(
  dir: string,
  state: LiveBuildState,
  event: PalmierOpEvent,
  mutations: Set<string>,
): LiveBuildState {
  if (event.event === "palmier_op" && event.tool
      && isLiveBuildMutationTool(event.tool)) {
    mutations.add(event.operationId);
    return patchLiveBuildState(dir, {
      operationsSeen: state.operationsSeen + 1,
    });
  }
  if (event.event === "palmier_op_result"
      && mutations.has(event.operationId) && event.status === "applied") {
    return patchLiveBuildState(dir, {
      operationsCompleted: state.operationsCompleted + 1,
    });
  }
  return state;
}

async function prepareRuntime(
  preflight: LiveBuildPreflight,
  resume: boolean,
  send: Send,
  signal?: AbortSignal,
): Promise<PreparedRuntime> {
  const parent = parentIdentity(preflight);
  assertLiveBuildRequest({
    dir: preflight.dir, planHash: preflight.planHash,
    doctrineHash: preflight.doctrineHash, projectId: preflight.projectId,
    projectPath: preflight.projectPath, parentTimelineId: parent.timelineId,
    parentFingerprint: parent.fingerprint,
  }, resume);
  send({ event: "live_build_progress", step: "candidate",
    message: resume ? "Restoring the retained editable candidate." : "Forking the verified parent into a visible editable candidate." });
  const prepared = await prepareLiveBuildCandidate(preflight, resume, signal);
  if (!sameIdentity(prepared.parent, parent)) {
    throw new Error("Palmier changed between live-build preflight and candidate fork.");
  }
  const state = prepareLiveBuildState({
    dir: preflight.dir, planHash: preflight.planHash,
    doctrineHash: preflight.doctrineHash, projectId: preflight.projectId,
    projectPath: preflight.projectPath, parentTimelineId: parent.timelineId,
    parentFingerprint: parent.fingerprint,
    candidateTimelineId: prepared.candidate.timelineId,
    candidateFingerprint: prepared.candidate.fingerprint,
    priorSessionId: preflight.priorSessionId,
  }, resume);
  const execution = { ...preflight, timelineId: prepared.candidate.timelineId,
    timelineFingerprint: prepared.candidate.fingerprint };
  const prompt = buildLiveBuildPrompt(execution, resume);
  const args = buildLiveBuildArgs({ prompt, sessionId: state.sessionId,
    resume: state.sessionEstablished, readDirs: readDirs(preflight) });
  send({ event: "live_build_started", runId: state.runId,
    sessionId: state.sessionId, timelineId: prepared.candidate.timelineId,
    message: "Claude is applying the approved plan directly to the visible Palmier candidate." });
  return { preflight, parent, candidate: prepared.candidate, state,
    sessionRecorded: state.sessionEstablished, args };
}

function processCallbacks(runtime: PreparedRuntime, send: Send) {
  const mutations = new Set<string>();
  return {
    onSession: () => {
      if (runtime.sessionRecorded) return;
      runtime.sessionRecorded = true;
      runtime.state = patchLiveBuildState(runtime.preflight.dir, {
        sessionEstablished: true,
      });
    },
    onEvent: (event: PalmierOpEvent) => {
      appendLiveBuildJournal(runtime.preflight.dir, { ...event });
      runtime.state = recordLiveBuildOperation(
        runtime.preflight.dir, runtime.state, event, mutations,
      );
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

async function executeCandidate(
  runtime: PreparedRuntime,
  send: Send,
  signal?: AbortSignal,
): Promise<ExecutedRuntime> {
  const result = await runLiveBuildProcess({
    args: runtime.args, cwd: process.cwd(), expectedSessionId: runtime.state.sessionId,
    signal, ...processCallbacks(runtime, send),
  });
  const operationCount = runtime.state.operationsCompleted;
  runtime.state = patchLiveBuildState(runtime.preflight.dir, {
      sessionEstablished: true,
  });
  emitLatency(result, send);
  const capture = captureLiveBuildQcAuthority({ preflight: runtime.preflight,
    parent: runtime.parent, sessionId: runtime.state.sessionId, operationCount });
  const checkpoint = await checkpointLiveBuildCandidate(
    runtime.preflight, capture.authorityPath, signal,
  );
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
    patchLiveBuildState(preflight.dir, {
      status: phase === "qc" ? "qc_failed" : signal?.aborted ? "interrupted" : "failed",
      error: error.message,
      sessionEstablished: runtime.sessionRecorded,
      ...(phase === "qc" ? { qcFailure: qcFailure(error, runtime) } : {}),
    });
    throw error;
  }
}
