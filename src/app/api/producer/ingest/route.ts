import { spawn, type ChildProcess } from "child_process";
import { mkdirSync, readFileSync } from "fs";
import path from "path";
import { NextRequest } from "next/server";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import { guardProjectMutation } from "../../_lib/project-mutation";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { cutPreviewLeaseGuard } from "../auto-edit/cut-preview-lease";
import type { ProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { workspaceRoot } from "../../_lib/workspace";
import { derror, dlog } from "@/lib/debug";
import { reconcileIntentCapabilities } from "@/lib/producer/intent-capabilities";
import type { ProjectIntent } from "@/lib/producer/intent-presets";
import { ingestArguments, json, parseRequest, type IngestRequest } from "./request";
import { assertIngestInputAuthority, assertSameIngestAuthority, existingIngestAuthority, type MutationAuthority } from "./authority";
import { requireSourceSetAdmission, type AssetManifest } from "@/lib/producer/types";
import {
  discardFreshIngestTarget,
  prepareIngestTarget,
  recordIngested,
  requestedIngestIntent,
  resolveIngestTarget,
  type IngestTarget,
  type SourceCopyProgress,
} from "./target";
export const maxDuration = 1800;
export const dynamic = "force-dynamic";
const SCRIPT_PATH = path.join(SCRIPTS_DIR, "producer", "ingest.py");
const MANIFEST_NAME = "asset_manifest.json";
const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache",
  Connection: "keep-alive",
  "X-Accel-Buffering": "no",
};

interface LeasedTarget {
  target: IngestTarget;
  authority: MutationAuthority;
  guard: () => void;
  release: () => void;
}
interface LiveIngest {
  aborter: AbortController;
  cancelled: boolean;
  committed: boolean;
  proc: ChildProcess | null;
}
interface Emitter {
  event: (value: Record<string, unknown>) => void;
  raw: (line: string) => void;
}
interface StreamContext {
  request: IngestRequest;
  leased: LeasedTarget;
  live: LiveIngest;
  controller: ReadableStreamDefaultController<Uint8Array>;
}

function initialMutationPath(request: IngestRequest): { root: string; producerDir: string } {
  const existing = existingIngestAuthority(request);
  if (existing) return existing;
  const root = workspaceRoot();
  mkdirSync(root, { recursive: true });
  return { root, producerDir: root };
}

function resolveLeasedTarget(request: IngestRequest): LeasedTarget | Response {
  const initial = initialMutationPath(request);
  const allocation = guardProjectMutation({
    projectRoot: initial.root,
    producerDir: initial.producerDir,
    operation: request.projectRoot || request.outDir ? "preparing this project's media" : "allocating a new project",
  });
  if (allocation.response) return allocation.response;
  let target: IngestTarget;
  try {
    target = resolveIngestTarget(request.inputPath, request.outDir, request.projectRoot);
  } catch (error) {
    allocation.lease.release();
    return json({ error: (error as Error).message }, 422);
  }
  if (!target.fresh || !target.projectRoot) return leaseTarget(target, initial, allocation.lease);
  let project: ReturnType<typeof guardProjectMutation>;
  try {
    project = guardProjectMutation({ projectRoot: target.projectRoot, producerDir: target.outDir,
      operation: "placing and preparing this project's media" });
  } finally { allocation.lease.release(); }
  if (!project.response) return leaseTarget(target, { root: target.projectRoot, producerDir: target.outDir }, project.lease);
  discardFreshIngestTarget(target);
  return project.response;
}

function leaseTarget(target: IngestTarget, authority: MutationAuthority, lease: ProjectMutationLease): LeasedTarget {
  try { return { target, authority, guard: cutPreviewLeaseGuard(authority.root, lease), release: lease.release }; }
  catch (error) { lease.release(); discardFreshIngestTarget(target); throw error; }
}

function createEmitter(controller: StreamContext["controller"]): Emitter {
  const encoder = new TextEncoder();
  const send = (value: string) => {
    try { controller.enqueue(encoder.encode(value)); } catch {}
  };
  return {
    event: (value) => send(`data: ${JSON.stringify(value)}\n\n`),
    raw: (line) => send(`data: ${line}\n\n`),
  };
}

function progressReporter(emit: Emitter): (progress: SourceCopyProgress) => void {
  let lastPercent = -1;
  let lastAt = 0;
  return (progress) => {
    const percent = progress.totalBytes > 0
      ? Math.min(100, Math.floor(progress.copiedBytes * 100 / progress.totalBytes))
      : 100;
    if (percent === lastPercent && Date.now() - lastAt < 250) return;
    lastPercent = percent;
    lastAt = Date.now();
    emit.event({ event: "source_copy_progress", ...progress, percent });
  };
}

function stopLiveIngest(live: LiveIngest): void {
  if (live.cancelled) return;
  live.cancelled = true;
  live.aborter.abort();
  if (live.proc) terminateProcessTree(live.proc);
}

function runIngestProcess(args: string[], emit: Emitter, live: LiveIngest): Promise<{
  code: number | null;
  stderr: string;
}> {
  return new Promise((resolve, reject) => {
    const proc = trackProcessTree(spawn(pythonInterpreter(), args, {
      env: { ...process.env },
      detached: shouldDetachProcessGroup(),
    }));
    live.proc = proc;
    let stdout = "";
    let stderr = "";
    let stderrLine = "";
    proc.stdout?.on("data", (data: Buffer) => {
      stdout += data.toString();
      const lines = stdout.split("\n");
      stdout = lines.pop() || "";
      for (const line of lines) if (line.trim()) emit.raw(line);
    });
    proc.stderr?.on("data", (data: Buffer) => {
      const text = data.toString();
      stderr = (stderr + text).slice(-1000);
      stderrLine += text;
      const lines = stderrLine.split("\n");
      stderrLine = lines.pop() || "";
      for (const line of lines) if (line.trim()) emit.event({ event: "log", stream: "stderr", text: line });
    });
    proc.once("error", (error) => {
      live.proc = null;
      reject(error);
    });
    proc.once("close", (code) => {
      live.proc = null;
      if (stdout.trim()) emit.raw(stdout);
      if (stderrLine.trim()) emit.event({ event: "log", stream: "stderr", text: stderrLine });
      resolve({ code, stderr });
    });
  });
}

function emitManifest(target: IngestTarget, intent: ProjectIntent | undefined, emit: Emitter): boolean {
  const manifestPath = path.join(target.manifestDir, MANIFEST_NAME);
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as AssetManifest;
  requireSourceSetAdmission(manifest);
  const requested = requestedIngestIntent(target, intent);
  const resolution = requested ? reconcileIntentCapabilities(requested, manifest) : undefined;
  const effective = recordIngested(target, resolution);
  for (const decision of resolution?.decisions ?? []) {
    emit.event({ event: "intent_capability", ...decision });
  }
  if (resolution && !resolution.ok) {
    emit.event({ event: "error", message: resolution.error });
    return false;
  }
  emit.event({
    event: "manifest",
    manifestPath,
    outDir: target.outDir,
    projectRoot: target.projectRoot,
    manifest,
    intent: effective ?? null,
    requestedIntent: resolution?.requestedIntent ?? requested ?? null,
    intentDecisions: resolution?.decisions ?? [],
  });
  return true;
}

function verifyPreparedTarget(leased: LeasedTarget, request: IngestRequest): void {
  leased.guard();
  const target = leased.target;
  const current = target.fresh ? existingIngestAuthority({ projectRoot: target.projectRoot! }) : existingIngestAuthority(request);
  assertSameIngestAuthority(current, leased.authority);
  // Fresh copies belong to the new project; referenced folders still retain their original owner.
  assertIngestInputAuthority({ inputPath: target.ingestInput,
    ...(target.projectRoot ? { projectRoot: target.projectRoot } : { outDir: target.outDir }) });
}

async function runStream(context: StreamContext): Promise<void> {
  const { request, leased, live, controller } = context;
  const emit = createEmitter(controller);
  const keepalive = setInterval(() => emit.raw(": keepalive"), 10_000);
  try {
    emit.event({ event: "source_placement_started", message: "Checking and placing source media" });
    const prepared = await prepareIngestTarget(
      leased.target,
      progressReporter(emit),
      live.aborter.signal,
    );
    leased.target = prepared.target;
    emit.event({
      event: prepared.placement === "referenced" ? "source_referenced" : "source_placement_complete",
      placement: prepared.placement,
      totalBytes: prepared.totalBytes,
      percent: 100,
    });
    if (live.cancelled) return;
    verifyPreparedTarget(leased, request);
    const manifestPath = path.join(prepared.target.manifestDir, MANIFEST_NAME);
    const args = ingestArguments({ script: SCRIPT_PATH, inputPath: prepared.target.ingestInput, manifestPath, request });
    dlog("producer:ingest", "spawn ingest.py", { args: args.slice(1), outDir: prepared.target.outDir });
    const result = await runIngestProcess(args, emit, live);
    if (live.cancelled) return;
    if (result.code !== 0) {
      emit.event({ event: "error", message: `ingest exited with code ${result.code}. ${result.stderr.slice(-500)}` });
      return;
    }
    verifyPreparedTarget(leased, request);
    emitManifest(prepared.target, request.intent, emit);
    live.committed = true;
  } catch (error) {
    if (!live.cancelled && (error as Error).name !== "AbortError") {
      derror("producer:ingest", "ingest failed", error);
      emit.event({ event: "error", message: (error as Error).message });
    }
  } finally {
    clearInterval(keepalive);
    leased.release();
    if (!live.committed) discardFreshIngestTarget(leased.target);
    try { controller.close(); } catch {}
  }
}

export async function POST(req: NextRequest) {
  let parsed: IngestRequest | Response;
  try { parsed = await parseRequest(req); } catch (error) {
    return json({ error: `Invalid request: ${(error as Error).message}` }, 400);
  }
  if (parsed instanceof Response) return parsed;
  let leased: LeasedTarget | Response;
  try { leased = resolveLeasedTarget(parsed); }
  catch (error) { return json({ error: (error as Error).message }, 422); }
  if (leased instanceof Response) return leased;
  const live: LiveIngest = {
    aborter: new AbortController(),
    cancelled: false,
    committed: false,
    proc: null,
  };
  const stop = () => stopLiveIngest(live);
  req.signal.addEventListener("abort", stop, { once: true });
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      void runStream({ request: parsed, leased, live, controller })
        .finally(() => req.signal.removeEventListener("abort", stop));
    },
    cancel: stop,
  });
  return new Response(stream, { headers: SSE_HEADERS });
}
