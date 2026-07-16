import { existsSync } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import {
  PROCESS_TERM_GRACE_MS,
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../../_lib/child-process-lifecycle";
import { pythonInterpreter } from "../../../_lib/spawn-python";
import { restoreAutoEditDoctrine } from "@/lib/server/auto-edit-doctrine";
import { restoreAutoEditPipeline } from "@/lib/server/auto-edit-pipeline-authority";
import { candidateReceipt } from "@/lib/server/palmier-candidate-qc";
import type { PalmierNativeQcAuthority } from "../../ai-edit/palmier-native-authority";
import type { PalmierLiveBuildQcAuthority } from "../../live-build/authority";
import type { CandidateQcAuthority, QcReviewer } from "./reviewer";
import { runCandidateQcAttempt, type CandidateQcCli } from "./attempt";
import {
  createReplacementCandidate,
  rejectFailedCandidate,
} from "./repair";

const CLI_TIMEOUT_MS = 30 * 60 * 1000;
const SHA256 = /^[0-9a-f]{64}$/;
type Send = (event: Record<string, unknown>) => void;

interface CliResult {
  code: number;
  verdict: Record<string, unknown>;
}

export interface QcDependencies {
  cli?: typeof runCli;
  review?: QcReviewer;
  authority?: (dir: string) => ReturnType<typeof authorityContext>;
  repair?: typeof createReplacementCandidate;
  rejectFailed?: typeof rejectFailedCandidate;
}

function lastObject(stdout: string): Record<string, unknown> {
  for (const line of stdout.trim().split("\n").filter(Boolean).reverse()) {
    try {
      const value = JSON.parse(line) as unknown;
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return value as Record<string, unknown>;
      }
    } catch {}
  }
  throw new Error("Palmier candidate QC returned no JSON verdict");
}

function runProcess(command: string, args: string[], signal?: AbortSignal): Promise<CliResult> {
  return new Promise((resolve) => {
    const child = trackProcessTree(spawn(command, args, {
      cwd: process.cwd(), env: { ...process.env }, detached: shouldDetachProcessGroup(),
    }));
    let stdout = "";
    let stderr = "";
    let settled = false;
    let forced: ReturnType<typeof setTimeout> | undefined;
    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (forced) clearTimeout(forced);
      signal?.removeEventListener("abort", abort);
      try { resolve({ code, verdict: lastObject(stdout) }); } catch {
        resolve({ code: code || 69, verdict: { ok: false, error: stderr || "QC produced no verdict" } });
      }
    };
    const abort = () => {
      terminateProcessTree(child);
      forced ??= setTimeout(() => finish(69), PROCESS_TERM_GRACE_MS + 1_000);
    };
    child.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    child.stderr.on("data", (data: Buffer) => (stderr = (stderr + data.toString()).slice(-4_000)));
    child.on("close", (code) => finish(code ?? 69));
    child.on("error", (error) => { stderr = error.message; finish(69); });
    const timer = setTimeout(abort, CLI_TIMEOUT_MS);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}

export function authorityContext(dir: string): {
  cli: string;
  payload: CandidateQcAuthority;
} {
  const candidate = candidateReceipt(dir);
  const live = candidate?.liveBuildAuthority as PalmierLiveBuildQcAuthority | undefined;
  const native = candidate?.nativeAuthority as PalmierNativeQcAuthority | undefined;
  const payload = live?.kind === "palmier-live-build-qc-authority" ? live : native;
  const common = payload?.schemaVersion === 1 && payload.ctx?.doctrine
    && payload.ctx.pipeline && payload.requestHash === candidate?.requestHash;
  const base = candidate?.base && typeof candidate.base === "object"
    && !Array.isArray(candidate.base) ? candidate.base as Record<string, unknown> : {};
  const nativeValid = Boolean(payload === native && native?.nativeInput
    && native.captureId === native.ctx.doctrine?.runId
    && native.captureId === native.ctx.pipeline?.runId
    && native.ctx.planPath === native.nativeInput.path
    && native.nativeInput.requestTextHash === native.requestHash);
  const liveValid = Boolean(payload === live && live?.liveInput
    && typeof live.captureId === "string" && live.captureId.length > 0
    && live.liveInput.parent.timelineId === base.timelineId
    && live.liveInput.parent.fingerprint === base.fingerprint
    && live.liveInput.sessionId.length > 0);
  if (!payload || !common || (!nativeValid && !liveValid)) {
    throw new Error("The candidate has no valid candidate-specific pinned QC authority. Create a fresh governed candidate.");
  }
  restoreAutoEditDoctrine(payload.ctx.doctrine!);
  const pipeline = restoreAutoEditPipeline(payload.ctx.pipeline!);
  if (!SHA256.test(payload.requestHash)) {
    throw new Error("The Palmier candidate has no valid governed request authority.");
  }
  const cli = path.join(
    pipeline.snapshotRoot, "scripts", "producer", "palmier", "native_qc_cli.py",
  );
  if (!existsSync(cli)) {
    throw new Error("This candidate predates pinned Palmier QC. Create a fresh governed candidate.");
  }
  return { cli, payload };
}

async function runCli(
  dir: string,
  action: "prepare" | "audit" | "finalize" | "reject" | "promote",
  inputPath?: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const authority = authorityContext(dir);
  const option = action === "finalize" ? "--finalize-approval"
    : action === "reject" ? "--reject-for-repair" : `--${action}`;
  const args = [authority.cli, dir, option, ...(inputPath ? [inputPath] : [])];
  const result = await runProcess(pythonInterpreter(), args, signal);
  if (result.code !== 0 || result.verdict.ok !== true) {
    const error = typeof result.verdict.error === "string" ? result.verdict.error : "Candidate QC failed.";
    const wrapped = new Error(error) as Error & { code?: number; status?: unknown };
    wrapped.code = result.code;
    wrapped.status = result.verdict.status;
    throw wrapped;
  }
  return result.verdict;
}

interface QcAttemptInput {
  dir: string;
  send: Send;
  dependencies: QcDependencies;
  context: ReturnType<typeof authorityContext>;
  signal?: AbortSignal;
}

function attemptInput(input: QcAttemptInput) {
  return { dir: input.dir, send: input.send, payload: input.context.payload,
    cli: (input.dependencies.cli ?? runCli) as CandidateQcCli,
    review: input.dependencies.review, signal: input.signal };
}

function repairableError(reason: unknown): Error & {
  candidateQcRepairable?: boolean;
} {
  return reason instanceof Error ? reason : new Error(String(reason));
}

interface RepairInput extends QcAttemptInput {
  authority: (dir: string) => ReturnType<typeof authorityContext>;
  nativePayload: PalmierNativeQcAuthority;
  error: Error;
}

async function replaceRejectedCandidate(
  input: RepairInput,
): Promise<Record<string, unknown>> {
  input.send({ event: "candidate_qc_progress", step: "repair",
    message: "QC rejected this candidate. Archiving it and creating one governed replacement from the preserved parent." });
  const cli = input.dependencies.cli ?? runCli;
  const repair = input.dependencies.repair ?? createReplacementCandidate;
  await repair({
    dir: input.dir,
    authority: input.nativePayload,
    error: input.error,
    reject: (reasonPath) => cli(input.dir, "reject", reasonPath, input.signal),
    signal: input.signal,
  });
  input.send({ event: "candidate_qc_progress", step: "replacement",
    message: "A separate replacement candidate is ready. Restarting the complete candidate QC sequence once." });
  const replacementContext = input.authority(input.dir);
  try {
    return await runCandidateQcAttempt(attemptInput({ ...input,
      context: replacementContext }));
  } catch (reason) {
    const second = repairableError(reason);
    if (second.candidateQcRepairable !== true) throw second;
    input.send({ event: "candidate_qc_progress", step: "repair_exhausted",
      message: "The one governed replacement also failed QC. Archiving it and preserving the verified parent; no third candidate will be created." });
    const rejectFailed = input.dependencies.rejectFailed ?? rejectFailedCandidate;
    await rejectFailed(input.dir,
      replacementContext.payload as PalmierNativeQcAuthority, second,
      (reasonPath) => cli(input.dir, "reject", reasonPath, input.signal));
    throw new Error(
      "Candidate QC stopped after one governed replacement. Both rejected candidates are archived, and the verified Palmier parent remains current. Nothing was promoted.",
    );
  }
}

export async function runCandidateQc(
  dir: string,
  send: Send,
  dependencies: QcDependencies = {},
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const authority = dependencies.authority ?? authorityContext;
  const context = authority(dir);
  if ("kind" in context.payload
      && context.payload.kind === "palmier-live-build-qc-authority") {
    return runCandidateQcAttempt(attemptInput({
      dir, send, dependencies, context, signal,
    }));
  }
  const nativePayload = context.payload as PalmierNativeQcAuthority;
  try {
    return await runCandidateQcAttempt(attemptInput({
      dir, send, dependencies, context, signal,
    }));
  } catch (reason) {
    const error = repairableError(reason);
    if (error.candidateQcRepairable !== true) throw error;
    return replaceRejectedCandidate({ dir, send, dependencies, context, signal,
      authority, nativePayload, error });
  }
}

/** Full-plan live builds are repaired in the retained session, never replaced wholesale. */
export async function runLiveBuildCandidateQc(
  dir: string,
  send: Send,
  dependencies: QcDependencies = {},
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const authority = dependencies.authority ?? authorityContext;
  const context = authority(dir);
  if (!("kind" in context.payload)
      || context.payload.kind !== "palmier-live-build-qc-authority") {
    throw new Error("Palmier candidate is not a retained-session live build.");
  }
  return runCandidateQcAttempt(attemptInput({
    dir, send, dependencies, context, signal,
  }));
}

export function promoteCandidate(
  dir: string,
  dependencies: QcDependencies = {},
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  return (dependencies.cli ?? runCli)(dir, "promote", undefined, signal);
}

export function parentDriftMessage(error: unknown): string {
  const item = error as Error & { code?: number; status?: unknown };
  if (item.code === 75 && item.status !== "waiting") {
    return "Palmier changed while this candidate was under review; nothing was overwritten.";
  }
  return item.message || "Palmier candidate QC failed; nothing was promoted.";
}
