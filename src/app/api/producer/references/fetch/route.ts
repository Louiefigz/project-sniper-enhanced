import { NextRequest } from "next/server";
import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import fs from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { removeProject, upsertProject } from "../../../_lib/projects-registry";
import { parseReferenceUrl } from "../../../_lib/reference-fetch-policy";
import { admitReferenceMedia } from "../../../_lib/reference-media-admission";
import {
  findReferenceById,
  stableReferenceId,
  writeReferenceSource,
} from "../../../_lib/reference-library";
import {
  admitReferenceVtt,
  type ReferenceTextAdmission,
} from "../../../_lib/reference-sidecar";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../../_lib/child-process-lifecycle";
import {
  cleanupFailedReferenceFetch,
  createProvisionalReferenceDir,
  promoteReferenceDir,
} from "../../../_lib/reference-fetch-storage";
import { derror, dlog } from "@/lib/debug";

export const maxDuration = 1800;
export const dynamic = "force-dynamic";

const SCRIPT_PATH = path.join(SCRIPTS_DIR, "producer", "study", "fetch_reference.py");

interface DownloadedReference {
  event?: string;
  video: string;
  title?: string;
  transcript?: string | null;
}

interface ReferencePromotionInput {
  event: DownloadedReference;
  provisional: string;
  url: URL;
  allowCookies: boolean;
  signal: AbortSignal;
}

interface FetchRuntime {
  url: URL;
  allowCookies: boolean;
  dir: string;
  args: string[];
  encoder: TextEncoder;
  child: ChildProcessWithoutNullStreams | null;
  controller: ReadableStreamDefaultController<Uint8Array> | null;
  cancelled: boolean;
  admissionAbort: AbortController;
  stdout: string;
  stderr: string;
  sawDone: boolean;
  sawTerminal: boolean;
  finalization: Promise<void> | null;
  keepalive: ReturnType<typeof setInterval> | null;
}

function rebindTranscript(
  transcript: string | null | undefined,
  dir: string,
  video: string,
): ReferenceTextAdmission | null {
  if (!transcript) return null;
  const source = path.join(dir, path.basename(transcript));
  const destination = path.join(
    dir, `${path.parse(video).name}.reference.vtt`,
  );
  return admitReferenceVtt(source, destination);
}

async function promoteDownloadedReference(
  input: ReferencePromotionInput,
): Promise<Record<string, unknown>> {
  const { event, provisional, url, allowCookies, signal } = input;
  const title = event.title || path.basename(event.video);
  let finalDir: string | null = null;
  let registered = false;
  try {
    fs.writeFileSync(
      path.join(provisional, ".sniper-admission-pending"),
      `${new Date().toISOString()}\n`,
      { flag: "wx" },
    );
    finalDir = promoteReferenceDir(provisional, title);
    const downloaded = path.join(finalDir, path.basename(event.video));
    const admission = await admitReferenceMedia(downloaded, finalDir, signal);
    const video = admission.snapshotPath;
    const transcript = rebindTranscript(event.transcript, finalDir, video);
    if (path.resolve(downloaded) !== path.resolve(video)) fs.unlinkSync(downloaded);
    writeReferenceSource(finalDir, {
      kind: "url", url: url.toString(), allowCookies,
      fetchedAt: new Date().toISOString(), transcript, admission,
    });
    fs.unlinkSync(path.join(finalDir, ".sniper-admission-pending"));
    upsertProject(finalDir, title, "reference");
    registered = true;
    const id = stableReferenceId(video);
    const reference = findReferenceById(id);
    reference.title = title;
    return {
      ...event, id, dir: finalDir, video,
      transcript: transcript?.path ?? null, reference,
    };
  } catch (error) {
    if (registered && finalDir) removeProject(finalDir);
    if (finalDir) cleanupFailedReferenceFetch(finalDir);
    else cleanupFailedReferenceFetch(provisional);
    throw error;
  }
}

function sendFetchEvent(runtime: FetchRuntime, payload: unknown): void {
  if (runtime.cancelled || !runtime.controller) return;
  try {
    runtime.controller.enqueue(
      runtime.encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
  } catch {}
}

function forwardFetchLine(runtime: FetchRuntime, line: string): void {
  if (!line.trim()) return;
  let event: DownloadedReference;
  try {
    event = JSON.parse(line) as DownloadedReference;
  } catch {
    sendFetchEvent(runtime, { event: "log", stream: "stdout", text: line });
    return;
  }
  if (event.event === "done" && event.video) {
    if (runtime.finalization) return;
    runtime.finalization = promoteDownloadedReference({
      event, provisional: runtime.dir, url: runtime.url,
      allowCookies: runtime.allowCookies,
      signal: runtime.admissionAbort.signal,
    }).then((promoted) => {
      runtime.sawDone = true;
      runtime.sawTerminal = true;
      sendFetchEvent(runtime, promoted);
    }).catch((error) => {
      runtime.sawTerminal = true;
      sendFetchEvent(runtime, {
        event: "error", message: (error as Error).message,
      });
    });
    return;
  }
  if (event.event === "error") runtime.sawTerminal = true;
  sendFetchEvent(runtime, event);
}

async function completeFetch(runtime: FetchRuntime, code: number | null): Promise<void> {
  if (runtime.stdout.trim()) forwardFetchLine(runtime, runtime.stdout);
  if (runtime.finalization) await runtime.finalization;
  if (!runtime.sawDone) cleanupFailedReferenceFetch(runtime.dir);
  if (!runtime.sawDone && !runtime.sawTerminal) {
    sendFetchEvent(runtime, {
      event: "error",
      message: `fetch exited without a video (code ${code}). ${runtime.stderr.slice(-400)}`.trim(),
    });
  }
  try { runtime.controller?.close(); } catch {}
}

function bindFetchProcess(runtime: FetchRuntime): void {
  const proc = runtime.child!;
  proc.stdout.on("data", (data: Buffer) => {
    runtime.stdout += data.toString();
    const lines = runtime.stdout.split("\n");
    runtime.stdout = lines.pop() || "";
    lines.forEach((line) => forwardFetchLine(runtime, line));
  });
  proc.stderr.on("data", (data: Buffer) => {
    const text = data.toString();
    runtime.stderr += text;
    process.stderr.write(text);
    for (const line of text.split("\n")) {
      if (line.trim()) {
        sendFetchEvent(runtime, { event: "log", stream: "stderr", text: line });
      }
    }
  });
  proc.on("close", (code) => {
    runtime.child = null;
    if (runtime.keepalive) clearInterval(runtime.keepalive);
    void completeFetch(runtime, code);
  });
  proc.on("error", (error) => {
    runtime.child = null;
    derror("producer:references", "failed to spawn fetch", error);
    if (runtime.keepalive) clearInterval(runtime.keepalive);
    cleanupFailedReferenceFetch(runtime.dir);
    sendFetchEvent(runtime, { event: "error", message: error.message });
    try { runtime.controller?.close(); } catch {}
  });
}

function startFetch(
  runtime: FetchRuntime,
  controller: ReadableStreamDefaultController<Uint8Array>,
): void {
  runtime.controller = controller;
  runtime.child = trackProcessTree(spawn(pythonInterpreter(), runtime.args, {
    env: { ...process.env },
    detached: shouldDetachProcessGroup(),
  }));
  runtime.keepalive = setInterval(() => {
    try {
      controller.enqueue(runtime.encoder.encode(": keepalive\n\n"));
    } catch {}
  }, 10_000);
  bindFetchProcess(runtime);
}

function cancelFetch(runtime: FetchRuntime): void {
  runtime.cancelled = true;
  runtime.admissionAbort.abort();
  const child = runtime.child;
  if (child && !child.killed) terminateProcessTree(child, 10_000);
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
  const dir = createProvisionalReferenceDir(url);
  const args = [SCRIPT_PATH, "--url", url.toString(), "--out-dir", dir];
  if (allowCookies) args.push("--allow-cookies");
  dlog("producer:references", "fetch spawn", { url: url.toString(), dir, allowCookies });

  const runtime: FetchRuntime = {
    url, allowCookies, dir, args, encoder: new TextEncoder(),
    child: null, controller: null, cancelled: false,
    admissionAbort: new AbortController(), stdout: "", stderr: "",
    sawDone: false, sawTerminal: false, finalization: null, keepalive: null,
  };
  const stream = new ReadableStream<Uint8Array>({
    start: (controller) => startFetch(runtime, controller),
    cancel: () => cancelFetch(runtime),
  });
  return new Response(stream, { headers: {
    "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
    Connection: "keep-alive", "X-Accel-Buffering": "no",
  } });
}
