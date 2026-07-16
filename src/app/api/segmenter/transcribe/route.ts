import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { dlog } from "@/lib/debug";

export const maxDuration = 600;
export const dynamic = "force-dynamic";

const SCRIPT_PATH = path.join(SCRIPTS_DIR, "transcribe.py");

export async function POST(req: NextRequest) {
  const { filePath } = await req.json();

  if (!filePath) {
    return new Response(JSON.stringify({ error: "No file path provided" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!existsSync(filePath)) {
    return new Response(JSON.stringify({ error: `File not found: ${filePath}` }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      dlog("segmenter:transcribe", "spawn transcribe.py", { interpreter: pythonInterpreter(), script: SCRIPT_PATH, filePath });
      const proc = spawn(pythonInterpreter(), [SCRIPT_PATH, filePath], {
        env: { ...process.env },
      });

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
          if (line.trim()) {
            if (line.includes('"done"')) dlog("segmenter:transcribe", "transcribe.py emitted done");
            controller.enqueue(encoder.encode(`data: ${line}\n\n`));
          }
        }
      });

      proc.stderr.on("data", (data: Buffer) => {
        const text = data.toString();
        stderrBuffer += text;
        process.stderr.write(`[transcribe.py stderr] ${text}`);
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ stderr: text.trim() })}\n\n`)
        );
      });

      proc.on("close", (code) => {
        clearInterval(keepalive);
        if (stdoutBuffer.trim()) {
          controller.enqueue(encoder.encode(`data: ${stdoutBuffer}\n\n`));
          stdoutBuffer = "";
        }
        console.log(`[transcribe.py] exited with code ${code}`);
        dlog("segmenter:transcribe", "transcribe.py closed", { code });
        if (code !== 0) {
          controller.enqueue(
            encoder.encode(
              `data: ${JSON.stringify({ error: `Process exited with code ${code}. ${stderrBuffer.slice(-500)}` })}\n\n`
            )
          );
        }
        controller.close();
      });

      proc.on("error", (err) => {
        clearInterval(keepalive);
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ error: err.message })}\n\n`)
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
