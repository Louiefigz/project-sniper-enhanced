import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { dlog, derror } from "@/lib/debug";
import { probeVideoMetadata } from "@/lib/server/clipper-media-probe";
import type { VideoMetadata } from "@/lib/clipper/types";
import { decorateTranscriptionWorkerLine } from "@/lib/clipper/transcription-stream";

export const maxDuration = 600;
export const dynamic = "force-dynamic";

// CLIPPER uses its own transcribe worker (stereo-channel isolation + diarization),
// kept distinct from SEGMENTER's scripts/transcribe.py.
const SCRIPT_PATH = path.join(SCRIPTS_DIR, "clipper", "clipper_transcribe.py");

function errorEvent(message: string): string {
  return `data: ${JSON.stringify({ error: message })}\n\n`;
}

export async function POST(req: NextRequest) {
  const { filePath, hostLavPath, guestLavPath } = await req.json();

  // Dual-lav mode: transcribe two individual mics (host + guest) instead of the
  // camera's audio. Both must be present and exist on disk; otherwise we fall
  // back to single-file transcription of `filePath` (the camera).
  const useLavs = !!(hostLavPath && guestLavPath);

  if (!filePath) {
    return new Response(JSON.stringify({ error: "No source video path provided" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (!existsSync(filePath)) {
    return new Response(JSON.stringify({ error: "Source video not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (useLavs) {
    for (const p of [hostLavPath, guestLavPath]) {
      if (!existsSync(p)) {
        return new Response(JSON.stringify({ error: `File not found: ${p}` }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
  }

  let media: VideoMetadata;
  try {
    media = await probeVideoMetadata(filePath);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    derror("clipper:transcribe", "source video probe failed", error);
    return new Response(JSON.stringify({ error: `Could not probe source video: ${detail}` }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
  }

  const args = useLavs
    ? [SCRIPT_PATH, "--lavs", hostLavPath, guestLavPath]
    : [SCRIPT_PATH, filePath];

  dlog("clipper:transcribe", "spawn python", { mode: useLavs ? "lavs" : "single", args: args.slice(1) });

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      const proc = spawn(pythonInterpreter(), args, {
        env: { ...process.env },
      });

      let stderrBuffer = "";
      let stdoutBuffer = "";
      let sawDone = false;
      let streamClosed = false;

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
          if (line.trim()) {
            const decorated = decorateTranscriptionWorkerLine(line, media);
            sawDone ||= decorated.done;
            controller.enqueue(encoder.encode(`data: ${decorated.payload}\n\n`));
          }
        }
      });

      proc.stderr.on("data", (data: Buffer) => {
        const text = data.toString();
        stderrBuffer += text;
        // Mirror the python worker's stderr (its [SNIPER:clipper] debug trace lives
        // here) straight to the dev terminal so the whole flow is visible in one place.
        process.stderr.write(text);
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ stderr: text.trim() })}\n\n`)
        );
      });

      proc.on("close", (code) => {
        if (streamClosed) return;
        dlog("clipper:transcribe", "python exit", { code, stderrTail: code !== 0 ? stderrBuffer.slice(-1500) : undefined });
        clearInterval(keepalive);
        if (stdoutBuffer.trim()) {
          const decorated = decorateTranscriptionWorkerLine(stdoutBuffer, media);
          sawDone ||= decorated.done;
          controller.enqueue(encoder.encode(`data: ${decorated.payload}\n\n`));
          stdoutBuffer = "";
        }
        if (code !== 0) {
          const detail = `Process exited with code ${code}. ${stderrBuffer.slice(-500)}`;
          controller.enqueue(encoder.encode(errorEvent(detail)));
        } else if (!sawDone) {
          controller.enqueue(encoder.encode(errorEvent("Transcription worker exited without a terminal done event")));
        }
        streamClosed = true;
        controller.close();
      });

      proc.on("error", (err) => {
        if (streamClosed) return;
        derror("clipper:transcribe", "failed to spawn python", err);
        clearInterval(keepalive);
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ error: err.message })}\n\n`)
        );
        streamClosed = true;
        controller.close();
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-store",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
