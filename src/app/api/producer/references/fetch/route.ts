import { NextRequest } from "next/server";
import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import fs from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { slugify, workspaceRoot } from "../../../_lib/workspace";
import { upsertProject } from "../../../_lib/projects-registry";
import { parseReferenceUrl } from "../../../_lib/reference-fetch-policy";
import {
  findReferenceById,
  stableReferenceId,
  writeReferenceSource,
} from "../../../_lib/reference-library";
import { derror, dlog } from "@/lib/debug";

export const maxDuration = 1800;
export const dynamic = "force-dynamic";

const SCRIPT_PATH = path.join(SCRIPTS_DIR, "producer", "study", "fetch_reference.py");

function referencesRoot(): string {
  return path.resolve(workspaceRoot(), "_references");
}

function provisionalDir(url: URL): string {
  const root = referencesRoot();
  const host = slugify(url.hostname.replace(/^www\./, "")) || "reference";
  const base = `.incoming-${host}-${Date.now().toString(36)}`;
  let dir = path.join(root, base);
  for (let n = 2; fs.existsSync(dir); n++) dir = path.join(root, `${base}-${n}`);
  return dir;
}

function finalReferenceDir(title: string): string {
  const root = referencesRoot();
  const base = slugify(title) || "reference";
  let dir = path.join(root, base);
  for (let n = 2; fs.existsSync(dir); n++) dir = path.join(root, `${base}-${n}`);
  return dir;
}

function cleanupFailedFetch(dir: string): void {
  try {
    const clean = path.resolve(dir);
    if (path.dirname(clean) !== referencesRoot()) return;
    fs.rmSync(clean, { recursive: true, force: true });
  } catch {}
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as
    { url?: string; allowCookies?: boolean } | null;
  const raw = (body?.url || "").trim();
  if (!raw) return Response.json({ error: "url is required" }, { status: 400 });
  if (body?.allowCookies !== undefined && typeof body.allowCookies !== "boolean") {
    return Response.json({ error: "allowCookies must be a boolean" }, { status: 400 });
  }
  let url: URL;
  try {
    url = parseReferenceUrl(raw);
  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 400 });
  }

  const allowCookies = body?.allowCookies === true;
  const dir = provisionalDir(url);
  fs.mkdirSync(dir, { recursive: true });
  const args = [SCRIPT_PATH, "--url", url.toString(), "--out-dir", dir];
  if (allowCookies) args.push("--allow-cookies");
  dlog("producer:references", "fetch spawn", { url: url.toString(), dir, allowCookies });

  const encoder = new TextEncoder();
  let child: ChildProcessWithoutNullStreams | null = null;
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) {
      const proc = spawn(pythonInterpreter(), args, { env: { ...process.env } });
      child = proc;
      let stdout = "";
      let stderr = "";
      let sawDone = false;
      let promotedDir: string | null = null;
      const send = (payload: unknown) => {
        if (cancelled) return;
        try { controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`)); } catch {}
      };
      const keepalive = setInterval(() => {
        try { controller.enqueue(encoder.encode(": keepalive\n\n")); } catch {}
      }, 10_000);

      const forwardLine = (line: string) => {
        if (!line.trim()) return;
        try {
          const event = JSON.parse(line) as {
            event?: string; video?: string; title?: string; transcript?: string | null;
          };
          if (event.event === "done" && event.video) {
            const title = event.title || path.basename(event.video);
            const finalDir = finalReferenceDir(title);
            fs.renameSync(dir, finalDir);
            promotedDir = finalDir;
            const video = path.join(finalDir, path.basename(event.video));
            const transcript = event.transcript
              ? path.join(finalDir, path.basename(event.transcript)) : null;
            writeReferenceSource(finalDir, {
              kind: "url", url: url.toString(), allowCookies,
              fetchedAt: new Date().toISOString(), transcript,
            });
            const id = stableReferenceId(video);
            const reference = findReferenceById(id);
            upsertProject(finalDir, title, "reference");
            reference.title = title;
            sawDone = true;
            send({ ...event, id, dir: finalDir, video, transcript, reference });
            return;
          }
          send(event);
        } catch {
          send({ event: "log", stream: "stdout", text: line });
        }
      };

      proc.stdout.on("data", (data: Buffer) => {
        stdout += data.toString();
        const lines = stdout.split("\n");
        stdout = lines.pop() || "";
        lines.forEach(forwardLine);
      });
      proc.stderr.on("data", (data: Buffer) => {
        const text = data.toString();
        stderr += text;
        process.stderr.write(text);
        for (const line of text.split("\n")) {
          if (line.trim()) send({ event: "log", stream: "stderr", text: line });
        }
      });
      proc.on("close", (code) => {
        child = null;
        clearInterval(keepalive);
        if (stdout.trim()) forwardLine(stdout);
        if (!sawDone) {
          cleanupFailedFetch(promotedDir ?? dir);
          send({ event: "error", message: `fetch exited without a video (code ${code}). ${stderr.slice(-400)}`.trim() });
        }
        try { controller.close(); } catch {}
      });
      proc.on("error", (error) => {
        child = null;
        derror("producer:references", "failed to spawn fetch", error);
        clearInterval(keepalive);
        cleanupFailedFetch(dir);
        send({ event: "error", message: error.message });
        try { controller.close(); } catch {}
      });
    },
    cancel() {
      cancelled = true;
      if (child && !child.killed) child.kill("SIGTERM");
    },
  });
  return new Response(stream, { headers: {
    "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
    Connection: "keep-alive", "X-Accel-Buffering": "no",
  } });
}
