import { NextRequest, NextResponse } from "next/server";
import { createReadStream, existsSync, statSync, unlinkSync } from "fs";
import { Readable } from "stream";
import path from "path";
import { tmpdir } from "os";
import { randomUUID } from "crypto";
import { spawnPython, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { dlog } from "@/lib/debug";

export const runtime = "nodejs";
export const maxDuration = 600;

const SCRIPT = path.join(SCRIPTS_DIR, "segmenter", "export_mp4.py");

interface ExportSegment {
  title: string;
  start: number;
  end: number;
}

export async function POST(req: NextRequest) {
  let body: { filePath?: unknown; segments?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { filePath, segments } = body;

  if (typeof filePath !== "string" || !existsSync(filePath)) {
    return NextResponse.json({ error: `Video not found: ${filePath}` }, { status: 400 });
  }
  if (!Array.isArray(segments) || segments.length === 0) {
    return NextResponse.json({ error: "No segments" }, { status: 400 });
  }

  const outputPath = path.join(tmpdir(), `clipper-export-${randomUUID()}.zip`);

  dlog("segmenter:export", "incoming request", {
    filePath,
    segments: (segments as ExportSegment[]).length,
    outputPath,
  });

  try {
    dlog("segmenter:export", "spawn export_mp4.py", { script: SCRIPT, filePath, outputPath });
    await spawnPython(SCRIPT, [filePath, JSON.stringify(segments as ExportSegment[]), outputPath]);

    if (!existsSync(outputPath)) {
      throw new Error("ffmpeg produced no output");
    }

    const size = statSync(outputPath).size;
    dlog("segmenter:export", "export complete", { outputPath, sizeBytes: size });
    const nodeStream = createReadStream(outputPath);
    nodeStream.on("close", () => {
      try { unlinkSync(outputPath); } catch {}
    });
    const webStream = Readable.toWeb(nodeStream) as unknown as ReadableStream<Uint8Array>;

    return new NextResponse(webStream, {
      headers: {
        "Content-Type": "application/zip",
        "Content-Length": String(size),
        "Content-Disposition": 'attachment; filename="segments.zip"',
        "Cache-Control": "private, no-store",
      },
    });
  } catch (e) {
    dlog("segmenter:export", "export error", e instanceof Error ? e.message : String(e));
    if (existsSync(outputPath)) {
      try { unlinkSync(outputPath); } catch {}
    }
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 500 }
    );
  }
}
