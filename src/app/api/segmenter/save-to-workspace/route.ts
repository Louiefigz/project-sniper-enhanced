import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { tmpdir } from "os";
import { randomUUID } from "crypto";
import { spawnPython, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { runCmd } from "../../_lib/run-cmd";
import { createProjectRoot, writeProjectJson } from "../../_lib/workspace";
import { upsertProject } from "../../_lib/projects-registry";
import { dlog } from "@/lib/debug";

export const runtime = "nodejs";
export const maxDuration = 600;

const SCRIPT = path.join(SCRIPTS_DIR, "segmenter", "export_mp4.py");

interface ExportSegment {
  title: string;
  start: number;
  end: number;
}

// SEGMENTER → WORKSPACE. Same stream-copy cuts as the zip download (the one
// export_mp4.py — the keyframe-snap invariant stays single-source), but written
// server-side into a NEW workspace project's segments/ dir instead of a browser
// download. Registers the PROJECT once (title carries the segment count); the
// producer page's Recent-edits card lists segments/ with "Ingest → edit".
export async function POST(req: NextRequest) {
  let body: { filePath?: unknown; segments?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const { filePath, segments } = body;
  if (typeof filePath !== "string" || !fs.existsSync(filePath)) {
    return NextResponse.json({ error: `Video not found: ${filePath}` }, { status: 400 });
  }
  if (!Array.isArray(segments) || segments.length === 0) {
    return NextResponse.json({ error: "No segments" }, { status: 400 });
  }

  const zipPath = path.join(tmpdir(), `sniper-workspace-${randomUUID()}.zip`);
  try {
    const projectRoot = createProjectRoot(path.basename(filePath));
    const segmentsDir = path.join(projectRoot, "segments");
    fs.mkdirSync(segmentsDir, { recursive: true });

    await spawnPython(SCRIPT, [filePath, JSON.stringify(segments as ExportSegment[]), zipPath]);
    const unzip = await runCmd("unzip", ["-o", zipPath, "-d", segmentsDir]);
    if (unzip.status !== 0) {
      throw new Error(`unzip exited ${unzip.status}: ${unzip.stderr.toString().slice(-300)}`);
    }

    writeProjectJson(projectRoot, {
      origin: "segmenter",
      history: [{ stage: "source", at: new Date().toISOString() }],
    });
    const names = fs.readdirSync(segmentsDir).filter((n) => n.endsWith(".mp4")).sort();
    upsertProject(projectRoot, `${path.basename(projectRoot)} · ${names.length} segments`);
    dlog("segmenter:workspace", "saved", { projectRoot, segments: names.length });
    return NextResponse.json({ ok: true, projectRoot, segments: names });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  } finally {
    if (fs.existsSync(zipPath)) {
      try { fs.unlinkSync(zipPath); } catch {}
    }
  }
}
