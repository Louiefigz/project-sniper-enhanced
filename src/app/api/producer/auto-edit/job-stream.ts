import { recoverAutoEditJob } from "@/lib/server/auto-edit-job-store";

const POLL_MS = 250;
const KEEPALIVE_MS = 10_000;

interface StreamSession {
  jobPath: string;
  expectedToken: string;
  encoder: TextEncoder;
  controller?: ReadableStreamDefaultController<Uint8Array>;
  poll?: ReturnType<typeof setInterval>;
  keepalive?: ReturnType<typeof setInterval>;
  closed: boolean;
  cursor: number;
  sawError: boolean;
  sawOutputs: boolean;
  sawWaiting: boolean;
  lastProgressKey?: string;
}

function terminalError(status: string, message: string): Record<string, unknown> {
  return { event: "error", status, message };
}

function closeSession(session: StreamSession): void {
  if (session.closed) return;
  session.closed = true;
  if (session.poll) clearInterval(session.poll);
  if (session.keepalive) clearInterval(session.keepalive);
  try { session.controller?.close(); } catch {}
}

function send(session: StreamSession, payload: Record<string, unknown>): void {
  if (session.closed) return;
  session.sawError ||= payload.event === "error";
  session.sawOutputs ||= payload.event === "outputs";
  session.sawWaiting ||= payload.event === "awaiting_cut_approval";
  try {
    session.controller?.enqueue(session.encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
  } catch {
    closeSession(session);
  }
}

function pump(session: StreamSession): void {
  try {
    const job = recoverAutoEditJob(session.jobPath);
    if (!job) throw new Error("Auto Edit job journal disappeared.");
    if (job.token !== session.expectedToken) {
      send(session, terminalError("interrupted", "This Auto Edit attempt was superseded by a newer Resume request."));
      closeSession(session);
      return;
    }
    session.cursor = Math.max(session.cursor, job.activeEventStartId - 1);
    for (const item of job.events) {
      if (item.id <= session.cursor || item.id < job.activeEventStartId) continue;
      send(session, item.payload);
      session.cursor = item.id;
    }
    const progressKey = `${job.phase}\u0000${job.message}`;
    if (job.status === "running" && progressKey !== session.lastProgressKey) {
      send(session, {
        event: "heartbeat",
        phase: job.phase,
        message: job.message,
        at: job.updatedAt,
      });
      session.lastProgressKey = progressKey;
    }
    if (job.status === "complete") {
      if (!session.sawOutputs) {
        send(session, { event: "outputs", outDir: job.ctx.dir, approved: true, recovered: true });
      }
      closeSession(session);
    }
    if (job.status === "failed" || job.status === "interrupted") {
      if (!session.sawError) send(session, terminalError(job.status, job.error ?? job.message));
      closeSession(session);
    }
    if (job.status === "awaiting_cut_approval") {
      if (!session.sawWaiting) send(session, { event: "awaiting_cut_approval",
        requestHash: job.cutApprovalRequest!.requestHash, message: job.message, recovered: true });
      closeSession(session);
    }
    if (job.status === "cut_accepted") {
      send(session, { event: "cut_accepted", requestHash: job.cutApprovalRequest!.requestHash,
        acceptanceHash: job.cutAcceptance!.acceptanceHash, message: job.message, recovered: true });
      closeSession(session);
    }
  } catch (error) {
    send(session, terminalError("failed", error instanceof Error ? error.message : String(error)));
    closeSession(session);
  }
}

function startSession(session: StreamSession): void {
  pump(session);
  if (session.closed) return;
  session.poll = setInterval(() => pump(session), POLL_MS);
  session.keepalive = setInterval(() => {
    try { session.controller?.enqueue(session.encoder.encode(": keepalive\n\n")); }
    catch { closeSession(session); }
  }, KEEPALIVE_MS);
}

export function autoEditJobStream(jobPath: string, expectedToken: string): ReadableStream {
  const session: StreamSession = {
    jobPath,
    expectedToken,
    encoder: new TextEncoder(),
    closed: false,
    cursor: 0,
    sawError: false,
    sawOutputs: false,
    sawWaiting: false,
    lastProgressKey: undefined,
  };
  return new ReadableStream({
    start(controller) {
      session.controller = controller;
      startSession(session);
    },
    cancel() {
      closeSession(session);
    },
  });
}
