import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { runAuditGate } from "../../_lib/audit-gate";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { lintEvent, resolveManifest, runLintGate } from "../auto-edit/chain";
import { AutoEditError } from "../auto-edit/stream";
import { assertSurgicalReviewCurrent } from "../ai-edit/finalize";
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
import { currentRenderGraphArgs } from "@/lib/server/current-render-graph-command";

export const maxDuration = 600;
export const dynamic = "force-dynamic";

const ASSEMBLE = path.join(SCRIPTS_DIR, "producer", "assemble.py");

// CONCURRENCY GUARD — one live re-render per dir, process-wide. A second POST
// for the same dir 409s instead of racing the first (two assemble.py runs
// would fight over final.mp4 / the refit-staged plan). Released when the
// stream closes (python exit OR client disconnect). The python-side
// .assemble.lock is the cross-process backstop; its "another re-render"
// failure surfaces through the same 409-style message in the editor.
const runningDirs = new Map<string, object>();

// The SMART re-render for the editor (one button, two speeds): assemble.py
// --auto-base compares the plan's non-graphics fields to base.fingerprint.json.
// Graphics-only edit → composite onto the existing base (~1 min). Cut/zoom/audio
// edit (or missing base) → it first re-runs render.py --skip-graphics (manifest
// recorded in the fingerprint file at the last base render, ~3 min), THEN
// composites — so a timeline edit actually lands instead of warning.
export async function POST(req: NextRequest) {
  const body = await req.json();
  const dir: string = (body.dir || "").replace(/\/$/, "");
  if (!dir) {
    return json({ error: "No render dir provided" }, 400);
  }
  if (runningDirs.has(dir) || producerRunActive(dir)) {
    return json({ error: "re-render already running for this dir" }, 409);
  }
  const baseVideo = path.join(dir, "base_final.mp4");
  const planPath = path.join(dir, "edit_plan.json");
  const outPath = path.join(dir, "final.mp4");
  const fingerprint = path.join(dir, "base.fingerprint.json");

  if (!existsSync(planPath)) {
    return json({ error: `No edit_plan.json in ${dir}` }, 404);
  }
  try {
    assertSurgicalReviewCurrent(planPath);
  } catch (error) {
    return json({ error: (error as Error).message }, 409);
  }
  if (!existsSync(baseVideo) && !existsSync(fingerprint)) {
    return json(
      { error: `No base render and no rebuild context in ${dir}. Run a base render (render.py --skip-graphics) once.` },
      409,
    );
  }
  // The plan_lint gate needs the manifest (fingerprint-recorded, else the
  // single ../source glob — same resolution as the auto-edit lane); assemble
  // then rebuilds from the SAME manifest the plan was linted against.
  let manifestPath: string;
  try {
    ({ manifestPath } = resolveManifest(dir));
  } catch (e) {
    if (e instanceof AutoEditError) return json({ error: e.message }, 409);
    throw e;
  }

  const rendererArgs = [
    ASSEMBLE, baseVideo, planPath, outPath, "--auto-base",
    "--manifest", manifestPath, "--require-source-set-admission",
  ];
  if (existsSync(fingerprint)) rendererArgs.push("--fingerprint", fingerprint);
  const args = currentRenderGraphArgs({
    phase: "assemble", producerDir: dir, planPath, manifestPath,
    basePath: baseVideo, outputPath: outPath, rendererArgs,
  });
  dlog("producer:assemble", "spawn assemble.py", { dir, args: args.slice(1) });
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(dir),
    producerDir: dir,
    operation: "rendering the updated timeline",
  });
  if (guarded.response) return guarded.response;
  try {
    assertTemplateUsageApprovalCurrent({ producerDir: dir, planPath, manifestPath });
  } catch (error) {
    guarded.lease.release();
    return json({ error: (error as Error).message }, 409);
  }
  let runToken: string;
  try {
    runToken = beginProducerRun(dir, "render", "validating", "Validating the saved edit plan before final rendering.");
  } catch (error) {
    guarded.lease.release();
    throw error;
  }

  // Token-guarded release: cancel() can free the guard during the pre-spawn
  // lint await, letting a successor POST re-acquire it — a request must never
  // delete a guard entry it no longer owns.
  const token = {};
  runningDirs.set(dir, token);
  let leaseReleased = false;
  const release = () => {
    if (runningDirs.get(dir) === token) runningDirs.delete(dir);
    if (leaseReleased) return;
    leaseReleased = true;
    guarded.lease.release();
  };

  const encoder = new TextEncoder();
  let proc: ReturnType<typeof spawn> | null = null;
  let cancelled = false;
  const stream = new ReadableStream({
    async start(controller) {
      // enqueue throws once the client disconnects — a vanished reader must not
      // abort the teardown (release + close still run on process exit).
      const send = (s: string) => {
        try {
          controller.enqueue(encoder.encode(s));
        } catch {}
      };
      const sendEvent = (obj: Record<string, unknown>) => send(`data: ${JSON.stringify(obj)}\n\n`);
      const keepalive = setInterval(() => send(`: keepalive\n\n`), 10000);
      const teardown = () => {
        clearInterval(keepalive);
        release();
        try {
          controller.close();
        } catch {}
      };

      // plan_lint gate BEFORE spawning — render.py's embedded gate never runs
      // on this path (assemble.py has no lint), so the route holds the line.
      let verdict;
      try {
        verdict = await runLintGate(planPath, manifestPath);
      } catch (error) {
        const message = `plan_lint failed to run: ${(error as Error).message}`;
        failProducerRun(dir, runToken, message);
        sendEvent({ event: "error", message });
        teardown();
        return;
      }
      sendEvent(lintEvent(verdict));
      if (!verdict.ok) {
        const message = `plan failed plan_lint: ${verdict.errors.slice(0, 3).join(" | ")}`;
        failProducerRun(dir, runToken, message);
        sendEvent({ event: "error", message });
        teardown();
        return;
      }

      // The client may have vanished during the lint await — cancel() already
      // released the guard, so spawning now would race a successor request.
      if (cancelled) {
        failProducerRun(dir, runToken, "Final render canceled before it started.");
        teardown();
        return;
      }

      updateProducerRun(dir, runToken, "rendering", "Plan passed validation; assembling the final video.");
      proc = spawn(pythonInterpreter(), args, { env: { ...process.env } });
      let stdoutBuffer = "";
      let stderrTail = "";

      // outputs FIRST (the deliverable exists), then Audit B — a QC fail
      // surfaces as an error event AFTER outputs, never instead of it.
      const finish = async (code: number | null) => {
        try {
          if (code !== 0) {
            const message = `assemble exited ${code}. ${stderrTail.slice(-400)}`;
            failProducerRun(dir, runToken, message);
            sendEvent({ event: "error", message });
            return;
          }
          sendEvent({ event: "outputs", outDir: dir });
          updateProducerRun(dir, runToken, "quality_check", "Final video exists; running post-render quality control.");
          const audit = await runAuditGate(dir);
          sendEvent(audit.event);
          if (audit.failure) {
            failProducerRun(dir, runToken, audit.failure);
            sendEvent({ event: "error", message: audit.failure });
          } else {
            completeProducerRun(dir, runToken);
          }
        } finally {
          teardown();
        }
      };

      proc.stdout!.on("data", (data: Buffer) => {
        stdoutBuffer += data.toString();
        const parts = stdoutBuffer.split("\n");
        stdoutBuffer = parts.pop() || "";
        for (const line of parts) {
          if (line.trim()) {
            appendProducerRunEvent(dir, runToken, line.slice(0, 240));
            send(`data: ${line}\n\n`);
          }
        }
      });

      proc.stderr!.on("data", (data: Buffer) => {
        const text = data.toString();
        stderrTail = (stderrTail + text).slice(-800);
        process.stderr.write(text);
      });

      proc.on("close", (code) => {
        if (stdoutBuffer.trim()) send(`data: ${stdoutBuffer}\n\n`);
        dlog("producer:assemble", "assemble.py closed", { code });
        void finish(code);
      });

      proc.on("error", (err) => {
        derror("producer:assemble", "failed to spawn assemble.py", err);
        failProducerRun(dir, runToken, err.message);
        sendEvent({ event: "error", message: err.message });
        teardown();
      });
    },
    // Client gone (tab closed / navigation): the re-render deliberately runs to
    // completion (killing ffmpeg mid-encode leaves a torn final.mp4), so the
    // dir guard must stay held until the python actually exits — proc 'close'
    // releases it after QC. Before spawn, start() observes cancelled after lint
    // and performs the same teardown; never release the project writer lease
    // from cancel while controller work is still unwinding.
    cancel() {
      cancelled = true;
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

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
