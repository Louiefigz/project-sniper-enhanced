import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import fs from "fs";
import path from "path";
import { NextRequest } from "next/server";
import { localWhisperPreflight } from "../../../_lib/local-whisper-preflight";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { backupStudyOutputs, finishStudyBackup } from "../../../_lib/reference-study-files";
import {
  canonicalStudyDir,
  findReferenceById,
  findWordTranscript,
  persistStyleProfile,
} from "../../../_lib/reference-library";

export const maxDuration = 3600;
export const dynamic = "force-dynamic";
const activeStudies = new Set<string>();

type Send = (payload: Record<string, unknown>) => void;

function workerEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  delete env.DEEPGRAM_API_KEY;
  env.SNIPER_TRANSCRIBE_PROVIDER = "local-whisper";
  return env;
}

function runWorker(args: string[], phase: string, send: Send,
                   setChild: (child: ChildProcessWithoutNullStreams | null) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonInterpreter(), args, {
      env: workerEnv(), detached: process.platform !== "win32",
    });
    setChild(child);
    let stdout = "";
    let stderr = "";
    const line = (raw: string) => {
      if (!raw.trim()) return;
      try {
        const payload = JSON.parse(raw) as Record<string, unknown>;
        const status = typeof payload.status === "string" ? payload.status : "progress";
        send({ event: "status", stage: `${phase}.${status}`, ...payload });
      } catch {
        send({ event: "log", stage: phase, stream: "stdout", text: raw });
      }
    };
    child.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
      const lines = stdout.split("\n");
      stdout = lines.pop() || "";
      lines.forEach(line);
    });
    child.stderr.on("data", (data: Buffer) => {
      const text = data.toString();
      stderr += text;
      for (const row of text.split("\n")) {
        if (row.trim()) send({ event: "log", stage: phase, stream: "stderr", text: row });
      }
    });
    child.on("error", reject);
    child.on("close", (code) => {
      setChild(null);
      if (stdout.trim()) line(stdout);
      if (code === 0) resolve();
      else reject(new Error(`${phase} exited ${code}: ${stderr.slice(-600)}`.trim()));
    });
  });
}

function terminateWorker(child: ChildProcessWithoutNullStreams | null): void {
  if (!child || child.killed) return;
  if (process.platform !== "win32" && child.pid) {
    try { process.kill(-child.pid, "SIGTERM"); return; } catch {}
  }
  child.kill("SIGTERM");
}

async function study(id: string, send: Send,
                     setChild: (child: ChildProcessWithoutNullStreams | null) => void) {
  const reference = findReferenceById(id);
  const previousHash = reference.profile?.source.sha256 ?? "";
  const studyDir = canonicalStudyDir(reference.video);
  fs.mkdirSync(studyDir, { recursive: true });
  let transcript = findWordTranscript(reference.video);
  send({ event: "status", stage: "resolve", id, video: reference.video });

  if (!transcript) {
    const whisper = localWhisperPreflight();
    if (whisper.ready) {
      transcript = path.join(studyDir, "transcript.json");
      const script = path.join(SCRIPTS_DIR, "producer", "study", "study_transcribe_local.py");
      await runWorker([script, reference.video, transcript], "transcribe", send, setChild);
    } else {
      send({ event: "status", stage: "transcribe.skipped", reason: whisper.detail });
    }
  } else {
    send({ event: "status", stage: "transcribe.reused", transcript });
  }

  const backup = backupStudyOutputs(studyDir);
  const script = path.join(SCRIPTS_DIR, "producer", "study", "study_deep.py");
  const args = [script, reference.video, studyDir];
  if (transcript) args.push("--transcript", transcript);
  let result: { profile: unknown; profilePath: string; deepStudyPath: string };
  try {
    await runWorker(args, "study", send, setChild);
    const completed = findReferenceById(id);
    if (!completed.profile || !completed.status.deepStudyPath) {
      throw new Error("study completed without a valid source-matched deep_study.json");
    }
    const profilePath = persistStyleProfile(completed);
    const persisted = findReferenceById(id);
    const nextHash = persisted.profile?.source.sha256 ?? "";
    if (reference.decision && /^[0-9a-f]{64}$/i.test(previousHash) && previousHash !== nextHash) {
      fs.rmSync(reference.status.decisionPath, { force: true });
    }
    result = { profile: persisted.profile, profilePath,
      deepStudyPath: completed.status.deepStudyPath };
  } catch (error) {
    finishStudyBackup(studyDir, backup, false);
    throw error;
  }
  finishStudyBackup(studyDir, backup, true);
  send({ event: "done", id, ...result });
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { id?: string } | null;
  const id = body?.id?.trim();
  if (!id) return Response.json({ error: "id is required" }, { status: 400 });
  if (activeStudies.has(id)) {
    return Response.json({ error: `study already running for ${id}` }, { status: 409 });
  }
  activeStudies.add(id);

  const encoder = new TextEncoder();
  let child: ChildProcessWithoutNullStreams | null = null;
  let cancelled = false;
  const stream = new ReadableStream({
    async start(controller) {
      const send: Send = (payload) => {
        if (cancelled) return;
        try { controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`)); } catch {}
      };
      const keepalive = setInterval(() => {
        try { controller.enqueue(encoder.encode(": keepalive\n\n")); } catch {}
      }, 10_000);
      try {
        await study(id, send, (next) => { child = next; });
      } catch (error) {
        send({ event: "error", message: (error as Error).message });
      } finally {
        clearInterval(keepalive);
        activeStudies.delete(id);
        try { controller.close(); } catch {}
      }
    },
    cancel() {
      cancelled = true;
      terminateWorker(child);
    },
  });
  return new Response(stream, { headers: {
    "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
    Connection: "keep-alive", "X-Accel-Buffering": "no",
  } });
}
