import { NextRequest, NextResponse } from "next/server";
import path from "node:path";
import { guardProjectMutation, mutationProjectRoot } from "../../../_lib/project-mutation";
import { canonicalPalmierDir, localPalmierRejection } from "../request";
import {
  PALMIER_NATIVE_QC_RUN_FILE,
  palmierCandidateQcState,
} from "@/lib/server/palmier-candidate-qc";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { captureProcessIdentity } from "@/lib/server/process-liveness";
import {
  parentDriftMessage,
  promoteCandidate,
  runCandidateQc,
} from "./runner";
import { runNativeCli } from "../../ai-edit/palmier-native-process";

export const dynamic = "force-dynamic";
export const maxDuration = 2400;

type Action = "run_qc" | "promote" | "discard";
type RunStatus = "running" | "complete" | "failed";

interface RunJournal {
  persist: (status: RunStatus, step: string, message: string, append?: boolean) => void;
  heartbeat: () => void;
}

function jsonError(error: unknown, status = 400): Response {
  return NextResponse.json({ error: error instanceof Error ? error.message : String(error) }, { status });
}

function requestDir(value: unknown): string {
  return canonicalPalmierDir(value);
}

export async function GET(req: NextRequest) {
  const rejection = localPalmierRejection(req);
  if (rejection) return jsonError(rejection.error, rejection.status);
  try {
    const dir = requestDir(req.nextUrl.searchParams.get("dir"));
    return NextResponse.json(palmierCandidateQcState(dir));
  } catch (error) {
    return jsonError(error);
  }
}

export async function POST(req: NextRequest) {
  const rejection = localPalmierRejection(req);
  if (rejection) return jsonError(rejection.error, rejection.status);
  const body = await req.json().catch(() => null) as { dir?: unknown; action?: unknown } | null;
  let dir: string;
  try { dir = requestDir(body?.dir); } catch (error) { return jsonError(error); }
  if (body?.action !== "run_qc" && body?.action !== "promote"
      && body?.action !== "discard") {
    return jsonError("action must be run_qc, promote, or discard");
  }
  const action = body.action as Action;
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(dir), producerDir: dir,
    operation: action === "run_qc" ? "reviewing a Palmier candidate"
      : action === "promote" ? "promoting a Palmier candidate"
        : "discarding a Palmier candidate and restoring its parent",
  });
  if (guarded.response) return guarded.response;
  return streamAction(dir, action, guarded.lease.release);
}

function streamAction(dir: string, action: Action, release: () => void): Response {
  const encoder = new TextEncoder();
  const journal = createJournal(dir, action);
  const initial = actionCopy(action);
  journal.persist("running", initial.step, initial.started);
  const stream = new ReadableStream({
    start(controller) {
      const heartbeat = setInterval(journal.heartbeat, 20_000);
      const send = (event: Record<string, unknown>) => {
        if (event.event === "candidate_qc_progress") {
          journal.persist("running", String(event.step ?? "checking"), String(event.message ?? ""));
        }
        try { controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); } catch {}
      };
      candidateOperation(dir, action, send).then((verdict) => {
        const done = actionCopy(action);
        journal.persist("complete", done.event, done.complete);
        send({ event: done.event, ...verdict, message: done.complete });
      }).catch((error) => {
        const message = parentDriftMessage(error);
        journal.persist("failed", "failed", message);
        send({ event: "error", message });
      }).finally(() => {
        clearInterval(heartbeat);
        release();
        try { controller.close(); } catch {}
      });
    },
    cancel() {
      // The server-owned transaction continues so Python can restore and
      // verify the canonical parent before releasing its Palmier lock.
    },
  });
  return new Response(stream, { headers: {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  } });
}

function candidateOperation(
  dir: string,
  action: Action,
  send: (event: Record<string, unknown>) => void,
): Promise<Record<string, unknown>> {
  if (action === "run_qc") return runCandidateQc(dir, send);
  if (action === "promote") return promoteCandidate(dir);
  return runNativeCli([dir, "--discard-candidate"]);
}

function actionCopy(action: Action) {
  if (action === "run_qc") return {
    step: "starting", event: "candidate_qc_approved",
    started: "Starting candidate QC from its saved checkpoint.",
    complete: "Candidate passed exported deterministic, composition, and editorial QC. Nothing was promoted.",
  };
  if (action === "promote") return {
    step: "promotion", event: "candidate_promoted",
    started: "Rechecking the approved candidate and parent before promotion.",
    complete: "The approved candidate is now the Palmier working source of truth.",
  };
  return {
    step: "discard", event: "candidate_discarded",
    started: "Archiving candidate evidence and restoring the exact parent.",
    complete: "Candidate receipt and evidence archived; the exact parent is the Palmier working source of truth.",
  };
}

function createJournal(dir: string, action: Action): RunJournal {
  const startedAt = new Date().toISOString();
  const ownerIdentity = captureProcessIdentity(process.pid);
  const runPath = path.join(dir, PALMIER_NATIVE_QC_RUN_FILE);
  const log: Array<{ at: string; step: string; message: string }> = [];
  let latest = { step: actionCopy(action).step, message: "" };
  const persist = (status: RunStatus, step: string, message: string, append = true) => {
    const at = new Date().toISOString();
    latest = { step, message };
    if (append && message) log.push({ at, step, message });
    atomicWriteJsonSync(runPath, {
      schemaVersion: 1, status, action, pid: process.pid, ownerIdentity, startedAt,
      updatedAt: at, step, message, log,
    });
  };
  return {
    persist,
    heartbeat: () => persist("running", latest.step, latest.message, false),
  };
}
