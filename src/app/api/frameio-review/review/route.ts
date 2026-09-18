import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { textReviewPaidFeatureError } from "../../_lib/paid-features";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { dlog, derror } from "@/lib/debug";

export const maxDuration = 600;
export const dynamic = "force-dynamic";

// review.py self-bootstraps its package path, so we can invoke it as a file.
const SCRIPT_PATH = path.join(SCRIPTS_DIR, "frameio", "review.py");
const MODELS = new Set(["claude-sonnet-4-6", "claude-haiku-4-5"]);

function validOptionalInt(value: unknown, max: number): boolean {
  return value == null || (Number.isInteger(value) && Number(value) >= 1 && Number(value) <= max);
}

function configError(input: Record<string, unknown>): string | null {
  const { fps, mode, fuzz, maxReps, maxFrames, hamming, model, confirmThreshold, yes } = input;
  if (typeof fps !== "number" || !Number.isFinite(fps) || fps < 0.1 || fps > 10) return "fps must be between 0.1 and 10";
  if (mode !== "visual" && mode !== "ocr") return "mode must be visual or ocr";
  if (typeof fuzz !== "number" || fuzz < 0 || fuzz > 100) return "fuzz must be between 0 and 100";
  if (typeof hamming !== "number" || hamming < 0 || hamming > 32) return "hamming must be between 0 and 32";
  if (!validOptionalInt(maxReps, 5000)) return "maxReps must be blank or an integer from 1 to 5000";
  if (!validOptionalInt(maxFrames, 1_000_000)) return "maxFrames must be blank or an integer from 1 to 1000000";
  if (typeof confirmThreshold !== "number" || !Number.isInteger(confirmThreshold) || confirmThreshold < 1 || confirmThreshold > 5000) return "confirmThreshold must be an integer from 1 to 5000";
  if (typeof model !== "string" || !MODELS.has(model)) return "unknown review model";
  if (typeof yes !== "boolean") return "yes must be a boolean";
  return null;
}

export async function POST(req: NextRequest) {
  const {
    filePath,
    fps = 1,
    mode = "visual",
    fuzz = 90,
    maxReps = null,
    maxFrames = null,
    hamming = 5,
    model = "claude-sonnet-4-6",
    confirmThreshold = 200,
    yes = false,
    paidApiConsent = false,
  } = await req.json();

  const invalid = textReviewPaidFeatureError(paidApiConsent)
    ?? configError({ fps, mode, fuzz, maxReps, maxFrames, hamming, model, confirmThreshold, yes });
  if (invalid) {
    return new Response(JSON.stringify({ error: invalid }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!filePath) {
    return new Response(JSON.stringify({ error: "No file path provided" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (!existsSync(filePath)) {
    return new Response(JSON.stringify({ error: "File not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  const args = [
    SCRIPT_PATH, "--server",
    "--input", filePath,
    "--fps", String(fps),
    "--mode", String(mode),
    "--fuzz", String(fuzz),
    "--hamming", String(hamming),
    "--model", String(model),
    "--confirm-threshold", String(confirmThreshold),
  ];
  if (maxReps != null) args.push("--max-reps", String(maxReps));
  if (maxFrames != null) args.push("--max-frames", String(maxFrames));
  if (yes) args.push("--yes");

  dlog("frameio:review", "spawn python", { args: args.slice(1) });

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      const proc = spawn(pythonInterpreter(), args, { env: { ...process.env } });

      let stderrBuffer = "";
      let stdoutBuffer = "";

      const keepalive = setInterval(() => {
        try {
          controller.enqueue(encoder.encode(`: keepalive\n\n`));
        } catch {}
      }, 10000);

      proc.stdout.on("data", (data: Buffer) => {
        stdoutBuffer += data.toString();
        const parts = stdoutBuffer.split("\n");
        stdoutBuffer = parts.pop() || "";
        for (const line of parts) {
          if (line.trim()) controller.enqueue(encoder.encode(`data: ${line}\n\n`));
        }
      });

      let stderrLineBuf = "";
      proc.stderr.on("data", (data: Buffer) => {
        const text = data.toString();
        stderrBuffer += text;
        // Mirror the python worker's [SNIPER:frameio] trace to the dev terminal…
        process.stderr.write(text);
        // …and forward each complete line over SSE as a `log` event so the tab's
        // Diagnostics panel shows the python trace inline (great for diagnosing).
        stderrLineBuf += text;
        const lines = stderrLineBuf.split("\n");
        stderrLineBuf = lines.pop() || "";
        for (const line of lines) {
          if (line.trim()) {
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify({ event: "log", stream: "stderr", text: line })}\n\n`),
            );
          }
        }
      });

      proc.on("close", (code) => {
        dlog("frameio:review", "python exit", {
          code,
          stderrTail: code !== 0 ? stderrBuffer.slice(-1500) : undefined,
        });
        clearInterval(keepalive);
        if (stderrLineBuf.trim()) {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify({ event: "log", stream: "stderr", text: stderrLineBuf })}\n\n`),
          );
          stderrLineBuf = "";
        }
        if (stdoutBuffer.trim()) {
          controller.enqueue(encoder.encode(`data: ${stdoutBuffer}\n\n`));
          stdoutBuffer = "";
        }
        if (code !== 0) {
          controller.enqueue(
            encoder.encode(
              `data: ${JSON.stringify({ event: "error", message: `Process exited with code ${code}. ${stderrBuffer.slice(-500)}` })}\n\n`,
            ),
          );
        }
        controller.close();
      });

      proc.on("error", (err) => {
        derror("frameio:review", "failed to spawn python", err);
        clearInterval(keepalive);
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ event: "error", message: err.message })}\n\n`),
        );
        controller.close();
      });
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
