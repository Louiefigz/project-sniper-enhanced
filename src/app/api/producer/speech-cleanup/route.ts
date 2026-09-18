import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync, readFileSync } from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { dlog, derror } from "@/lib/debug";

export const maxDuration = 600;
export const dynamic = "force-dynamic";

// One-click speech cleanup: spawn edit/speech_cleanup.py against the manifest
// the base was rendered from (resolved via base.fingerprint.json — never an
// arbitrary path) and forward its NDJSON stdout as SSE. The CLI's contract:
// args <manifest.json> [--source-id], stdout NDJSON ending
// {"status":"done","cutTrack":[...],"segments":N,"removedS":X}. The UI shows
// that proposal and the operator applies it to plan.cutTrack (undo-able).
const CLEANUP = path.join(SCRIPTS_DIR, "producer", "edit", "speech_cleanup.py");
const PRODUCER_DIR = path.join(SCRIPTS_DIR, "producer");

function resolveManifest(dir: string): string {
  const fingerprintPath = path.join(dir, "base.fingerprint.json");
  if (!existsSync(fingerprintPath)) {
    throw new Error(`No base.fingerprint.json in ${dir} — render a base first`);
  }
  const fp = JSON.parse(readFileSync(fingerprintPath, "utf-8")) as { manifestPath?: string };
  if (!fp.manifestPath || !existsSync(fp.manifestPath)) {
    throw new Error(`base.fingerprint.json manifestPath missing or gone: ${fp.manifestPath}`);
  }
  return fp.manifestPath;
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const dir: string = (body.dir || "").replace(/\/$/, "");
  if (!dir) return json({ error: "Missing dir" }, 400);
  if (dir.split("/").includes("..")) return json({ error: "Forbidden" }, 403);
  if (!existsSync(CLEANUP)) {
    return json({ error: "speech_cleanup.py is not available yet (edit lane in flight)" }, 409);
  }

  let manifestPath: string;
  try {
    manifestPath = resolveManifest(dir);
  } catch (e) {
    return json({ error: (e as Error).message }, 409);
  }

  const args = [CLEANUP, manifestPath];
  dlog("producer:speech-cleanup", "spawn", { dir, manifestPath });

  // speech_cleanup.py lives in edit/ and imports sibling producer modules —
  // spawn with scripts/producer on PYTHONPATH (the subprocess invariant).
  const env: NodeJS.ProcessEnv = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH ? `${PRODUCER_DIR}:${env.PYTHONPATH}` : PRODUCER_DIR;

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      const proc = spawn(pythonInterpreter(), args, { env });
      let stdoutBuffer = "";
      let stderrTail = "";
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

      proc.stderr.on("data", (data: Buffer) => {
        const text = data.toString();
        stderrTail = (stderrTail + text).slice(-800);
        process.stderr.write(text);
      });

      proc.on("close", (code) => {
        clearInterval(keepalive);
        if (stdoutBuffer.trim()) controller.enqueue(encoder.encode(`data: ${stdoutBuffer}\n\n`));
        dlog("producer:speech-cleanup", "closed", { code });
        if (code !== 0) {
          const evt = { event: "error", message: `speech_cleanup exited ${code}. ${stderrTail.slice(-400)}` };
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(evt)}\n\n`));
        }
        controller.close();
      });

      proc.on("error", (err) => {
        derror("producer:speech-cleanup", "spawn failed", err);
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

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
