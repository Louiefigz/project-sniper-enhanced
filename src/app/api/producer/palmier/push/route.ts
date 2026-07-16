import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { dlog, derror } from "@/lib/debug";
import { autoEditQcApproval, findManifest, palmierRenderPath } from "../_lib";
import { guardProjectMutation, mutationProjectRoot } from "../../../_lib/project-mutation";
import { assertTemplateUsageApprovalCurrent } from "@/lib/server/template-usage-approval";

export const maxDuration = 900;
export const dynamic = "force-dynamic";

const PUSH = path.join(SCRIPTS_DIR, "producer", "palmier", "push.py");
const LINT = path.join(SCRIPTS_DIR, "producer", "plan_lint.py");

interface SyncSpec {
  dir: string;
  args: string[];
}

function runPy(args: string[]): Promise<{ stdout: string; code: number }> {
  return new Promise((resolve) => {
    const proc = spawn(pythonInterpreter(), args, { env: { ...process.env } });
    let stdout = "";
    proc.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    proc.stderr.on("data", (d: Buffer) => process.stderr.write(d));
    proc.on("close", (code) => resolve({ stdout, code: code ?? 1 }));
    proc.on("error", () => resolve({ stdout, code: 1 }));
  });
}

// Explicit, one-way sync. The Python process owns crash-safe per-dir + global
// locks, so repeated requests reach its latest-wins queue even across HMR or
// multiple dev servers. Every accepted plan passes plan_lint before MCP access.
export async function POST(req: NextRequest) {
  const { dir: rawDir } = (await req.json()) as { dir?: string };
  const dir = (rawDir || "").replace(/\/$/, "");
  if (!dir) return json({ error: "No dir provided" }, 400);
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(dir),
    producerDir: dir,
    operation: "updating the Palmier working revision",
  });
  if (guarded.response) return guarded.response;
  const prepared = await prepareSync(dir);
  if (prepared instanceof Response) {
    guarded.lease.release();
    return prepared;
  }
  return syncResponse(prepared, guarded.lease.release);
}

async function prepareSync(dir: string): Promise<SyncSpec | Response> {
  if (!dir) return json({ error: "No dir provided" }, 400);
  const planPath = path.join(dir, "edit_plan.json");
  if (!existsSync(planPath)) return json({ error: `No edit_plan.json in ${dir}` }, 404);
  const manifestPath = findManifest(dir);
  if (!manifestPath) return json({ error: `No asset manifest for ${dir}` }, 404);
  try {
    assertTemplateUsageApprovalCurrent({ producerDir: dir, planPath, manifestPath });
  } catch (error) {
    return json({ error: (error as Error).message }, 409);
  }
  const qcApproval = autoEditQcApproval(dir);
  if (!qcApproval.approved) return json({ error: qcApproval.reason }, 409);
  const lintBlocked = await lintGate(planPath, manifestPath);
  if (lintBlocked) return lintBlocked;
  const parityBlocked = await parityGate(planPath, manifestPath);
  if (parityBlocked) return parityBlocked;
  const slug = path.basename(path.dirname(dir)) || "sniper-push";
  const args = [PUSH, planPath, manifestPath, "--name", slug,
    "--export", palmierRenderPath(dir)];
  dlog("producer:palmier", "spawn shadow sync", { dir, args: args.slice(1) });
  return { dir, args };
}

async function lintGate(planPath: string, manifestPath: string): Promise<Response | null> {
  const lint = await runPy([LINT, planPath, manifestPath]);
  try {
    const verdict = JSON.parse(lint.stdout.trim()) as { ok?: boolean; errors?: string[] };
    if (verdict.ok) return null;
    return json(
      { error: "plan_lint rejected the plan — fix before syncing", errors: verdict.errors ?? [] },
      422,
    );
  } catch {
    return json({ error: `plan_lint produced no verdict (exit ${lint.code})` }, 500);
  }
}

async function parityGate(planPath: string, manifestPath: string): Promise<Response | null> {
  const preflight = await runPy([PUSH, planPath, manifestPath, "--preflight"]);
  try {
    const line = preflight.stdout.trim().split("\n").filter(Boolean).pop() ?? "";
    const verdict = JSON.parse(line) as {
      ok?: boolean;
      blocked?: string;
      translatorBlocked?: string | null;
      parity?: unknown;
    };
    if (verdict.ok) return null;
    return json({
      error: verdict.blocked || "Palmier full-editability gate rejected the plan",
      translatorBlocked: verdict.translatorBlocked ?? null,
      parity: verdict.parity ?? null,
    }, 422);
  } catch {
    return json({ error: `Palmier parity preflight produced no verdict (exit ${preflight.code})` }, 500);
  }
}

function syncResponse(spec: SyncSpec, release: () => void): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start: (controller) => startSync(controller, encoder, spec, release),
    // The Python transaction deliberately survives a disconnected browser: its
    // finally restores the human timeline and marks any partial fork FAILED.
    cancel() {},
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

function startSync(
  controller: ReadableStreamDefaultController,
  encoder: TextEncoder,
  spec: SyncSpec,
  release: () => void,
): void {
  const proc = spawn(pythonInterpreter(), spec.args, { env: { ...process.env } });
  let stdoutBuffer = "";
  let stderrTail = "";
  const send = (value: string) => safeSend(controller, encoder.encode(value));
  const keepalive = setInterval(() => send(`: keepalive\n\n`), 10000);
  proc.stdout.on("data", (data: Buffer) => {
    stdoutBuffer += data.toString();
    const parts = stdoutBuffer.split("\n");
    stdoutBuffer = parts.pop() || "";
    for (const line of parts) if (line.trim()) send(`data: ${line}\n\n`);
  });
  proc.stderr.on("data", (data: Buffer) => {
    const value = data.toString();
    stderrTail = (stderrTail + value).slice(-800);
    process.stderr.write(value);
  });
  proc.on("close", (code) => {
    clearInterval(keepalive);
    release();
    if (stdoutBuffer.trim()) send(`data: ${stdoutBuffer}\n\n`);
    dlog("producer:palmier", "shadow sync closed", { code });
    send(`data: ${JSON.stringify(closeEvent(code, spec.dir, stderrTail))}\n\n`);
    safeClose(controller);
  });
  proc.on("error", (error) => {
    derror("producer:palmier", "failed to spawn shadow sync", error);
    clearInterval(keepalive);
    release();
    send(`data: ${JSON.stringify({ event: "error", message: error.message })}\n\n`);
    safeClose(controller);
  });
}

function safeSend(controller: ReadableStreamDefaultController, value: Uint8Array): void {
  try { controller.enqueue(value); } catch {}
}

function safeClose(controller: ReadableStreamDefaultController): void {
  try { controller.close(); } catch {}
}

function closeEvent(code: number | null, dir: string, stderr: string): Record<string, unknown> {
  if (code === 0) return { event: "outputs", palmierRender: palmierRenderPath(dir) };
  if (code === 75) return { event: "waiting", message: "Palmier sync queued or waiting" };
  return { event: "error", message: `sync exited ${code}. ${stderr.slice(-400)}` };
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
