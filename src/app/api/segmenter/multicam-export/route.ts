import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "fs";
import path from "path";
import { tmpdir } from "os";
import { randomUUID } from "crypto";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { register } from "../../_lib/multicam-store";
import { dlog } from "@/lib/debug";

export const runtime = "nodejs";
export const maxDuration = 3600;
export const dynamic = "force-dynamic";

const SCRIPT_PATH = path.join(SCRIPTS_DIR, "segmenter", "multicam_pipeline.py");

interface ExportSegment {
  title: string;
  start: number;
  end: number;
}

interface Body {
  acamPath?: unknown;
  bcamPath?: unknown;
  ccamPath?: unknown;
  lav1Path?: unknown;
  lav2Path?: unknown;
  segments?: unknown;
}

function basename(p: string): string {
  const name = p.split("/").pop() ?? "output";
  return name.replace(/\.\w+$/, "") || "output";
}

export async function POST(req: NextRequest) {
  let body: Body;
  try {
    body = (await req.json()) as Body;
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const { acamPath, bcamPath, ccamPath, lav1Path, lav2Path, segments } = body;

  if (typeof acamPath !== "string" || !existsSync(acamPath)) {
    return new Response(JSON.stringify({ error: `A-cam not found: ${String(acamPath)}` }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  const hasB = typeof bcamPath === "string" && bcamPath.length > 0;
  const hasC = typeof ccamPath === "string" && ccamPath.length > 0;
  const hasLav1 = typeof lav1Path === "string" && lav1Path.length > 0;
  const hasLav2 = typeof lav2Path === "string" && lav2Path.length > 0;
  if (!hasB && !hasC && !hasLav1 && !hasLav2) {
    return new Response(JSON.stringify({
      error: "Provide at least one of bcamPath / ccamPath / lav1Path / lav2Path",
    }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (hasB && !existsSync(bcamPath as string)) {
    return new Response(JSON.stringify({ error: `B-cam not found: ${bcamPath}` }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (hasC && !existsSync(ccamPath as string)) {
    return new Response(JSON.stringify({ error: `C-cam not found: ${ccamPath}` }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (hasLav1 && !existsSync(lav1Path as string)) {
    return new Response(JSON.stringify({ error: `Lav 1 not found: ${lav1Path}` }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (hasLav2 && !existsSync(lav2Path as string)) {
    return new Response(JSON.stringify({ error: `Lav 2 not found: ${lav2Path}` }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (!Array.isArray(segments) || segments.length === 0) {
    return new Response(JSON.stringify({ error: "No segments" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const exportSegments: ExportSegment[] = (segments as ExportSegment[]).map((s) => ({
    title: String(s.title ?? ""),
    start: Number(s.start),
    end: Number(s.end),
  }));

  const runId = randomUUID();
  const workDir = mkdtempSync(path.join(tmpdir(), `multicam-export-${runId}-`));
  const segmentsPath = path.join(workDir, "segments.json");
  const outdir = path.join(workDir, "out");
  const zipPath = path.join(tmpdir(), `multicam-zip-${runId}.zip`);
  writeFileSync(segmentsPath, JSON.stringify(exportSegments));

  const baseFilename = `${basename(acamPath)}_multicam.zip`;

  dlog("segmenter:multicam", "incoming request", {
    acamPath,
    bcamPath: hasB ? bcamPath : undefined,
    ccamPath: hasC ? ccamPath : undefined,
    lav1Path: hasLav1 ? lav1Path : undefined,
    lav2Path: hasLav2 ? lav2Path : undefined,
    segments: exportSegments.length,
    runId,
    baseFilename,
  });

  const args = [
    SCRIPT_PATH,
    "--acam", acamPath,
    "--segments", segmentsPath,
    "--outdir", outdir,
    "--zip-out", zipPath,
  ];
  if (hasB) args.push("--bcam", bcamPath as string);
  if (hasC) args.push("--ccam", ccamPath as string);
  if (hasLav1) args.push("--lav1", lav1Path as string);
  if (hasLav2) args.push("--lav2", lav2Path as string);

  const cleanup = () => {
    try { rmSync(workDir, { recursive: true, force: true }); } catch {}
  };

  const encoder = new TextEncoder();
  let proc: ReturnType<typeof spawn> | null = null;
  let keepalive: ReturnType<typeof setInterval> | null = null;
  const stream = new ReadableStream({
    start(controller) {
      const send = (obj: unknown) => {
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));
        } catch {}
      };

      dlog("segmenter:multicam", "spawn multicam_pipeline.py", { interpreter: pythonInterpreter(), args });
      const child = spawn(pythonInterpreter(), args, { env: { ...process.env } });
      proc = child;

      let stderrBuffer = "";
      let stdoutBuffer = "";

      keepalive = setInterval(() => {
        try { controller.enqueue(encoder.encode(`: keepalive\n\n`)); } catch {}
      }, 10000);

      child.stdout.on("data", (data: Buffer) => {
        stdoutBuffer += data.toString();
        const parts = stdoutBuffer.split("\n");
        stdoutBuffer = parts.pop() ?? "";
        for (const line of parts) {
          if (line.trim()) {
            controller.enqueue(encoder.encode(`data: ${line}\n\n`));
          }
        }
      });

      child.stderr.on("data", (data: Buffer) => {
        const text = data.toString();
        stderrBuffer += text;
        process.stderr.write(`[multicam_pipeline.py stderr] ${text}`);
        send({ stderr: text.trim() });
      });

      child.on("close", (code) => {
        if (keepalive) clearInterval(keepalive);
        if (stdoutBuffer.trim()) {
          controller.enqueue(encoder.encode(`data: ${stdoutBuffer}\n\n`));
          stdoutBuffer = "";
        }
        console.log(`[multicam_pipeline.py] exited with code ${code}`);
        if (code === 0 && existsSync(zipPath)) {
          const downloadId = register(zipPath, baseFilename);
          dlog("segmenter:multicam", "pipeline finished, zip registered", { code, downloadId, filename: baseFilename, zipPath });
          send({ status: "ready", downloadId, filename: baseFilename });
        } else {
          dlog("segmenter:multicam", "pipeline failed", { code });
          send({
            error: `Pipeline exited with code ${code}. ${stderrBuffer.slice(-500)}`,
          });
          if (existsSync(zipPath)) {
            try { rmSync(zipPath, { force: true }); } catch {}
          }
        }
        cleanup();
        controller.close();
      });

      child.on("error", (err) => {
        if (keepalive) clearInterval(keepalive);
        dlog("segmenter:multicam", "spawn error", err.message);
        send({ error: err.message });
        cleanup();
        controller.close();
      });
    },
    // Client disconnected (navigated away / aborted). Kill the render so it
    // doesn't keep burning CPU, and clean up the temp dir + any partial zip.
    cancel() {
      dlog("segmenter:multicam", "client disconnected, killing pipeline", { runId });
      if (keepalive) clearInterval(keepalive);
      if (proc) { try { proc.kill("SIGTERM"); } catch {} }
      if (existsSync(zipPath)) {
        try { rmSync(zipPath, { force: true }); } catch {}
      }
      cleanup();
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
