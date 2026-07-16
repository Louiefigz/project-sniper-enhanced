import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync, mkdtempSync, writeFileSync, rmSync, mkdirSync, renameSync } from "fs";
import os from "os";
import path from "path";
import { runAuditGate } from "../../_lib/audit-gate";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { upsertProject } from "../../_lib/projects-registry";
import { dlog, derror } from "@/lib/debug";
import {
  appendProducerRunEvent,
  beginProducerRun,
  completeProducerRun,
  failProducerRun,
  producerRunActive,
  updateProducerRun,
} from "@/lib/server/producer-run-registry";
import { guardProjectMutation, mutationProjectRoot } from "../../_lib/project-mutation";
import { assertTemplateUsageApprovalCurrent } from "@/lib/server/template-usage-approval";

export const maxDuration = 600;
export const dynamic = "force-dynamic";

const RENDER = path.join(SCRIPTS_DIR, "producer", "render.py");
const ASSEMBLE = path.join(SCRIPTS_DIR, "producer", "assemble.py");

// EDITOR-READY fresh render (two stages, one stream):
//   1. render.py --skip-graphics <plan> <manifest> <outDir>  → the graphics-free
//      BASE master + base.fingerprint.json (manifestPath) + base_plan.json +
//      edit_plan.json + captions sidecar. We rename its final.mp4 →
//      base_final.mp4 so it becomes the assemble base.
//   2. assemble.py <base_final> <edit_plan> <final.mp4> --fingerprint --auto-base
//      → composites graphicsTrack (+ music) onto the base.
// A monolithic render left no base artifacts, so EVERY editor affordance
// (assemble / words / speech-cleanup / source-frame) 409'd on a fresh render.
// This way each new render opens FULLY working in the editor and re-renders
// on the fast assemble path. Both processes' NDJSON streams through as SSE,
// stage-tagged. render.py cleans its OWN temp workdir only when --workdir is
// omitted; we pass one under os.tmpdir(), so THIS route owns its cleanup.

interface Emitter {
  raw: (line: string) => void; // one NDJSON line → SSE data frame, verbatim
  event: (obj: Record<string, unknown>) => void; // synthetic event frame
}

interface StageExit {
  code: number | null;
  stderrTail: string;
}

/** The stream's live-child tracker so cancel() can kill before any cleanup. */
interface LiveChild {
  proc: ReturnType<typeof spawn> | null;
  cancelled: boolean;
}

/**
 * SIGTERM the child's whole PROCESS GROUP (the stage is spawned detached so
 * python + its ffmpeg children share one), escalating to SIGKILL after 5s.
 * Never touches the filesystem — the awaited 'close' in POST runs the cleanup
 * strictly AFTER exit, so the workdir is never removed under a live child.
 */
function killStage(proc: ReturnType<typeof spawn>): void {
  if (proc.exitCode !== null || !proc.pid) return;
  try {
    process.kill(-proc.pid, "SIGTERM");
  } catch {
    try {
      proc.kill("SIGTERM");
    } catch {}
  }
  const hard = setTimeout(() => {
    if (proc.exitCode === null && proc.pid) {
      try {
        process.kill(-proc.pid, "SIGKILL");
      } catch {}
    }
  }, 5000);
  hard.unref();
}

/** Spawn one pipeline stage; forward NDJSON stdout + stderr log frames. */
function runStage(args: string[], stage: string, emit: Emitter, live: LiveChild): Promise<StageExit> {
  return new Promise((resolve, reject) => {
    // detached → own process group, so a cancel can kill python AND the
    // ffmpeg children it spawned (see killStage).
    const proc = spawn(pythonInterpreter(), args, { env: { ...process.env }, detached: true });
    live.proc = proc;
    let stdoutBuffer = "";
    let stderrTail = "";
    let stderrLineBuf = "";

    proc.stdout.on("data", (data: Buffer) => {
      stdoutBuffer += data.toString();
      const parts = stdoutBuffer.split("\n");
      stdoutBuffer = parts.pop() || "";
      for (const line of parts) if (line.trim()) emit.raw(line);
    });

    proc.stderr.on("data", (data: Buffer) => {
      const text = data.toString();
      stderrTail = (stderrTail + text).slice(-800);
      process.stderr.write(text);
      stderrLineBuf += text;
      const lines = stderrLineBuf.split("\n");
      stderrLineBuf = lines.pop() || "";
      for (const line of lines) {
        if (line.trim()) emit.event({ event: "log", stream: "stderr", stage, text: line });
      }
    });

    proc.on("close", (code) => {
      live.proc = null;
      if (stdoutBuffer.trim()) emit.raw(stdoutBuffer);
      if (stderrLineBuf.trim()) {
        emit.event({ event: "log", stream: "stderr", stage, text: stderrLineBuf });
      }
      dlog("producer:render", `${stage} closed`, { code });
      resolve({ code, stderrTail });
    });

    proc.on("error", (err) => {
      live.proc = null;
      reject(err);
    });
  });
}

export async function POST(req: NextRequest) {
  const { planJson, planPath, manifestPath, outDir } = await req.json();

  if (!manifestPath || !existsSync(manifestPath)) {
    return jsonResponse({ error: `Manifest not found: ${manifestPath}` }, 404);
  }
  if (!outDir) {
    return jsonResponse({ error: "No output dir provided" }, 400);
  }
  if (!planJson && !planPath) {
    return jsonResponse({ error: "No plan provided (planJson or planPath)" }, 400);
  }
  if (producerRunActive(outDir)) {
    return jsonResponse({ error: "another Producer job is already running for this project" }, 409);
  }

  mkdirSync(outDir, { recursive: true });
  const out = String(outDir).replace(/\/$/, "");
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(out),
    producerDir: out,
    operation: "rendering this project's video",
  });
  if (guarded.response) return guarded.response;
  let leaseReleased = false;
  const releaseLease = () => {
    if (leaseReleased) return;
    leaseReleased = true;
    guarded.lease.release();
  };
  // One temp workdir holds intermediates AND (when given inline) the plan file,
  // so a single cleanup removes everything this route created.
  let workDir: string;
  let resolvedPlanPath = planPath;
  try {
    workDir = mkdtempSync(path.join(os.tmpdir(), "producer-render-"));
    if (!resolvedPlanPath) {
      resolvedPlanPath = path.join(workDir, "edit_plan.json");
      const planText = typeof planJson === "string" ? planJson : JSON.stringify(planJson, null, 2);
      writeFileSync(resolvedPlanPath, planText);
    }
  } catch (error) {
    releaseLease();
    throw error;
  }
  try { assertTemplateUsageApprovalCurrent({ producerDir: out, planPath: resolvedPlanPath!, manifestPath }); }
  catch (error) { rmSync(workDir, { recursive: true, force: true }); releaseLease();
    return jsonResponse({ error: (error as Error).message }, 409); }
  const baseVideo = path.join(out, "base_final.mp4");
  const finalVideo = path.join(out, "final.mp4");
  const outPlanPath = path.join(out, "edit_plan.json"); // written by render.py
  const fingerprint = path.join(out, "base.fingerprint.json");
  let runToken: string;
  try {
    runToken = beginProducerRun(out, "render", "rendering", "Rendering the saved edit plan into a base video.");
  } catch (error) {
    rmSync(workDir, { recursive: true, force: true });
    releaseLease();
    throw error;
  }

  const baseArgs = [RENDER, resolvedPlanPath, manifestPath, out, "--workdir", workDir, "--skip-graphics"];
  const asmArgs = [ASSEMBLE, baseVideo, outPlanPath, finalVideo, "--fingerprint", fingerprint, "--auto-base"];
  dlog("producer:render", "editor-ready render", { base: baseArgs.slice(1), assemble: asmArgs.slice(1) });

  const cleanup = () => rmSync(workDir, { recursive: true, force: true });
  const encoder = new TextEncoder();
  const live: LiveChild = { proc: null, cancelled: false };

  const stream = new ReadableStream({
    async start(controller) {
      // enqueue throws once the client disconnects — swallow it so a vanished
      // reader can't abort the teardown.
      const send = (s: string) => {
        try { controller.enqueue(encoder.encode(s)); } catch {}
      };
      const emit: Emitter = {
        raw: (line) => {
          appendProducerRunEvent(out, runToken, line.slice(0, 240));
          send(`data: ${line}\n\n`);
        },
        event: (obj) => {
          const message = String(obj.note ?? obj.message ?? obj.status ?? obj.event ?? "render event");
          appendProducerRunEvent(out, runToken, message);
          send(`data: ${JSON.stringify(obj)}\n\n`);
        },
      };
      const keepalive = setInterval(() => send(`: keepalive\n\n`), 10000);

      try {
        emit.event({ status: "base_render_start", stage: "base", note: "rendering the graphics-free base (editor-ready)" });
        const base = await runStage(baseArgs, "base", emit, live);
        if (live.cancelled || base.code !== 0) {
          const message = live.cancelled ? "Render canceled." : `base render exited with code ${base.code}. ${base.stderrTail.slice(-500)}`;
          failProducerRun(out, runToken, message);
          if (!live.cancelled) emit.event({ event: "error", message });
          return;
        }
        // The graphics-free master becomes the assemble base; assemble writes
        // the deliverable back to final.mp4.
        renameSync(finalVideo, baseVideo);
        updateProducerRun(out, runToken, "rendering", "Base video complete; assembling graphics and final audio.");
        emit.event({ status: "assemble_start", stage: "assemble", note: "compositing graphics onto the base" });
        const asm = await runStage(asmArgs, "assemble", emit, live);
        if (live.cancelled || asm.code !== 0) {
          const message = live.cancelled ? "Render canceled." : `assemble exited with code ${asm.code}. ${asm.stderrTail.slice(-500)}`;
          failProducerRun(out, runToken, message);
          if (!live.cancelled) emit.event({ event: "error", message });
          return;
        }
        // outputs FIRST — the deliverable exists even if Audit B then fails.
        emit.event({ event: "outputs", outDir: out });
        // Register the finished render in the PROJECT BROWSER (~/.project-sniper).
        try {
          upsertProject(out, path.basename(out));
        } catch (err) {
          derror("producer:render", "projects registry upsert failed", err);
        }
        updateProducerRun(out, runToken, "quality_check", "Final video exists; running post-render quality control.");
        // Audit B (post-render QC) — render.py's own audit_stage is skipped on
        // --skip-graphics, so this route gates the assembled deliverable itself.
        emit.event({ status: "audit_start", stage: "audit", note: "Audit B post-render QC" });
        const audit = await runAuditGate(out);
        emit.event(audit.event);
        if (audit.failure) {
          failProducerRun(out, runToken, audit.failure);
          emit.event({ event: "error", message: audit.failure });
        } else {
          completeProducerRun(out, runToken);
        }
      } catch (err) {
        derror("producer:render", "editor-ready render failed", err);
        failProducerRun(out, runToken, (err as Error).message);
        emit.event({ event: "error", message: (err as Error).message });
      } finally {
        clearInterval(keepalive);
        cleanup(); // runs strictly after the awaited stage exits — never under a live child
        releaseLease();
        try { controller.close(); } catch {}
      }
    },
    // Client disconnected mid-render. NEVER rm the shared workdir while a
    // spawned python is still running (a live ffmpeg writing into a vanished
    // dir corrupts the out dir's artifacts) — kill the stage's process group
    // first; the awaited close in start() then runs the one cleanup. Only when
    // no child is live (between stages / already finished) is rm safe here.
    cancel() {
      live.cancelled = true;
      if (live.proc) killStage(live.proc);
      else cleanup();
    },
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

function jsonResponse(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
