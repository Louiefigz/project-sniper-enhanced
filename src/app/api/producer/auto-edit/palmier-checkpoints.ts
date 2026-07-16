import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import type { AutoEditCtx, Send } from "./stream";

const CHECKPOINT = path.join(SCRIPTS_DIR, "producer", "palmier", "checkpoint_cli.py");
const PUSH = path.join(SCRIPTS_DIR, "producer", "palmier", "push.py");
const TIMEOUT_MS = 10 * 60 * 1_000;

export type PalmierCheckpointStage = "cut" | "plan" | "revision" | "render";

export interface PalmierCheckpointSpec {
  stage: PalmierCheckpointStage;
  round: number;
  mediaPath?: string;
}

/**
 * Working checkpoints are courtesy publishes: they NEVER reject the job.
 * committed = the checkpoint (or a superseding manual head) is live in Palmier;
 * deferred  = Palmier is busy/closed/ineligible, nothing was attempted or lost;
 * warned    = the publish failed, Palmier keeps its previous state, run continues.
 */
export interface PalmierCheckpointOutcome {
  status: "committed" | "warned" | "deferred";
  reason?: string;
  detail?: Record<string, unknown>;
}

/** checkpoint_cli.py exits 75 when Palmier is closed/unreachable (PalmierWaiting). */
const WAITING_EXIT_CODE = 75;

export interface PalmierProcessResult {
  code: number;
  event: Record<string, unknown>;
  stderr: string;
  timedOut: boolean;
}

type ProcessRunner = (
  args: string[],
  onEvent: (event: Record<string, unknown>) => void,
) => Promise<PalmierProcessResult>;

interface ManagedWorkspace {
  eligible: boolean;
  reason: string;
  fatal: boolean;
}

function objectLine(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function managedWorkspace(dir: string): ManagedWorkspace {
  const file = path.join(dir, "palmier.sync.json");
  if (!existsSync(file)) {
    return { eligible: false, reason: "Palmier workspace is not open yet.", fatal: false };
  }
  try {
    const state = objectLine(readFileSync(file, "utf8"));
    if (!state || state.schemaVersion !== 4) {
      return { eligible: false, reason: "Palmier workspace state is invalid.", fatal: true };
    }
    if (state.workspaceMode !== "managed-draft") {
      return {
        eligible: false,
        reason: "Palmier is already canonical; plan checkpoints are paused.",
        fatal: false,
      };
    }
    if (state.ownership === "palmier") {
      return {
        eligible: false,
        reason: "Palmier contains a human-owned revision.",
        fatal: false,
      };
    }
    return { eligible: true, reason: "", fatal: false };
  } catch (error) {
    return {
      eligible: false,
      reason: `Palmier workspace state is unreadable: ${(error as Error).message}`,
      fatal: true,
    };
  }
}

function savedTimelineId(dir: string): string | undefined {
  try {
    const state = objectLine(readFileSync(path.join(dir, "palmier.sync.json"), "utf8"));
    return typeof state?.latestTimelineId === "string" ? state.latestTimelineId : undefined;
  } catch {
    return undefined;
  }
}

export function checkpointCommand(ctx: AutoEditCtx, spec: PalmierCheckpointSpec): string[] {
  const args = [CHECKPOINT, ctx.planPath, ctx.manifestPath, ctx.dir,
    "--stage", spec.stage, "--round", String(spec.round)];
  if (spec.mediaPath) args.push("--media", spec.mediaPath);
  return args;
}

export function approvedMirrorCommand(ctx: AutoEditCtx): string[] {
  const name = path.basename(path.dirname(ctx.dir)) || "sniper-push";
  return [PUSH, ctx.planPath, ctx.manifestPath, "--name", name,
    "--export", path.join(ctx.dir, "final.palmier.mp4")];
}

export function runPalmierProcess(
  args: string[],
  onEvent: (event: Record<string, unknown>) => void,
): Promise<PalmierProcessResult> {
  return new Promise((resolve) => {
    const child = trackProcessTree(spawn(pythonInterpreter(), args, {
      detached: shouldDetachProcessGroup(),
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    }));
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let last: Record<string, unknown> = {};
    const consume = (flush = false) => {
      const rows = stdout.split("\n");
      stdout = flush ? "" : rows.pop() ?? "";
      for (const row of rows) {
        const event = objectLine(row.trim());
        if (!event) continue;
        last = event;
        onEvent(event);
      }
    };
    const timer = setTimeout(() => {
      timedOut = true;
      terminateProcessTree(child);
    }, TIMEOUT_MS);
    child.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
      consume();
    });
    child.stderr.on("data", (data: Buffer) => {
      stderr = (stderr + data.toString()).slice(-2_000);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      consume(true);
      resolve({ code: code ?? 1, event: last, stderr, timedOut });
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ code: 1, event: { reason: error.message }, stderr, timedOut });
    });
  });
}

function detailEvent(send: Send, stage: string) {
  return (detail: Record<string, unknown>) => {
    const status = String(detail.status ?? "checkpoint_progress");
    const transition = status === "checkpoint_transition_ready"
      ? `${String(detail.kind)} transition preview ready (${String(detail.fidelity)})`
      : undefined;
    send({
      event: "palmier_checkpoint_detail", stage, status,
      timelineId: detail.timelineId, index: detail.index,
      kind: detail.kind, fidelity: detail.fidelity, path: detail.path,
      message: detail.reason ?? detail.warning ?? transition,
    });
  };
}

function skipped(send: Send, stage: string, reason: string): void {
  send({ event: "palmier_checkpoint_skipped", stage, message: reason });
}

/** Only the approved mirror may fail loudly; working checkpoints warn/defer. */
function failed(send: Send, stage: string, reason: string): never {
  const message = `Palmier ${stage} checkpoint failed: ${reason}`;
  send({ event: "palmier_checkpoint_failed", stage, message });
  throw new Error(message);
}

function deferred(send: Send, stage: string, reason: string): PalmierCheckpointOutcome {
  send({
    event: "palmier_checkpoint_deferred", stage, status: "deferred",
    message: `Palmier ${stage} checkpoint deferred: ${reason}`,
  });
  return { status: "deferred", reason };
}

function warned(send: Send, stage: string, reason: string): PalmierCheckpointOutcome {
  send({
    event: "palmier_checkpoint_warned", stage, status: "warned",
    message: `Palmier ${stage} checkpoint was not published (${reason}); `
      + "Palmier keeps its previous state and the run continues.",
  });
  return { status: "warned", reason };
}

async function runRequiredCheckpoint(
  args: string[],
  stage: string,
  send: Send,
  runner: ProcessRunner,
): Promise<PalmierProcessResult> {
  try {
    return await runner(args, detailEvent(send, stage));
  } catch (error) {
    return failed(send, stage, (error as Error).message);
  }
}

function advancedWorkingHead(
  send: Send,
  spec: PalmierCheckpointSpec,
  event: Record<string, unknown>,
): void {
  send({
    event: "palmier_working_head_advanced",
    stage: spec.stage,
    round: spec.round,
    timelineId: event.timelineId,
    fingerprint: event.fingerprint,
    authority: "palmier",
    reason: event.reason,
    message: "Palmier changed manually. That readback is now the working source of truth, and the stale plan checkpoint will not replace it. Future governed AI edits will start from the Palmier version.",
  });
}

export async function publishPalmierWorkingCheckpoint(
  ctx: AutoEditCtx,
  spec: PalmierCheckpointSpec,
  send: Send,
  runner: ProcessRunner = runPalmierProcess,
): Promise<PalmierCheckpointOutcome> {
  if (!existsSync(path.join(ctx.dir, "palmier.sync.json"))) {
    return { status: "deferred", reason: "Palmier workspace is not open yet." };
  }
  const workspace = managedWorkspace(ctx.dir);
  if (!workspace.eligible) {
    if (workspace.fatal) return warned(send, spec.stage, workspace.reason);
    skipped(send, spec.stage, workspace.reason);
    return { status: "deferred", reason: workspace.reason };
  }
  send({ event: "palmier_checkpoint_started", stage: spec.stage, round: spec.round });
  let result: PalmierProcessResult;
  try {
    result = await runner(checkpointCommand(ctx, spec), detailEvent(send, spec.stage));
  } catch (error) {
    return warned(send, spec.stage, (error as Error).message);
  }
  if (result.code === 0 && !result.timedOut
      && result.event.status === "checkpoint_superseded") {
    advancedWorkingHead(send, spec, result.event);
    return { status: "committed", detail: { superseded: true,
      timelineId: result.event.timelineId } };
  }
  const waiting = !result.timedOut && (result.code === WAITING_EXIT_CODE
    || (result.code === 0 && result.event.status === "checkpoint_waiting"));
  if (waiting) {
    return deferred(send, spec.stage, String(result.event.reason
      ?? "Palmier is busy or unreachable; the checkpoint will publish on a later round."));
  }
  if (result.code !== 0 || result.timedOut || result.event.status !== "checkpoint_ready") {
    const reason = result.timedOut ? "Palmier checkpoint exceeded its 10-minute safety limit."
      : String(result.event.reason ?? (result.stderr.trim()
        || "Palmier checkpoint was not published."));
    return warned(send, spec.stage, reason);
  }
  send({ event: "palmier_checkpoint_ready", stage: spec.stage, round: spec.round,
    timelineId: result.event.timelineId, timelineName: result.event.timelineName,
    reused: result.event.reused === true, omissions: result.event.omissions ?? [],
    limitations: result.event.limitations ?? [],
    fidelityFindings: result.event.fidelityFindings ?? [] });
  return { status: "committed" };
}

export async function publishApprovedPalmierMirror(
  ctx: AutoEditCtx,
  send: Send,
  runner: ProcessRunner = runPalmierProcess,
): Promise<void> {
  if (!existsSync(path.join(ctx.dir, "palmier.sync.json"))) return;
  const workspace = managedWorkspace(ctx.dir);
  if (!workspace.eligible) {
    if (workspace.fatal) failed(send, "qc-approved", workspace.reason);
    skipped(send, "qc-approved", workspace.reason);
    return;
  }
  send({ event: "palmier_checkpoint_started", stage: "qc-approved", round: 0 });
  const result = await runRequiredCheckpoint(
    approvedMirrorCommand(ctx), "qc-approved", send, runner,
  );
  const ready = result.code === 0 && !result.timedOut
    && ["done", "sync_done"].includes(String(result.event.status));
  if (!ready) {
    const reason = result.timedOut ? "Final Palmier mirror exceeded its 10-minute safety limit."
      : String(result.event.reason ?? result.event.error ?? (result.stderr.trim()
        || "Final Palmier mirror was not published."));
    failed(send, "qc-approved", reason);
  }
  send({ event: "palmier_checkpoint_ready", stage: "qc-approved", round: 0,
    timelineId: savedTimelineId(ctx.dir), verified: true });
}
