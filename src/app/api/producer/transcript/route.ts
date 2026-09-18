import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// Serve a render's OUTPUT-time transcript for the editor's transcript panel.
// Longform renders emit captions.srt (output-time cues) even when captions are
// NOT burned, so it's the right source for the word/line track. Read-only, and
// locked to .srt files named captions.srt.
interface Cue {
  start: number;
  end: number;
  text: string;
}

function srtTime(stamp: string): number {
  // 00:00:12,340 -> seconds
  const m = stamp.trim().match(/(\d+):(\d+):(\d+)[.,](\d+)/);
  if (!m) return 0;
  return +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000;
}

function parseSrt(text: string): Cue[] {
  const cues: Cue[] = [];
  for (const block of text.split(/\r?\n\r?\n/)) {
    const lines = block.split(/\r?\n/).filter(Boolean);
    const tl = lines.find((l) => l.includes("-->"));
    if (!tl) continue;
    const [a, b] = tl.split("-->");
    const body = lines.slice(lines.indexOf(tl) + 1).join(" ").trim();
    if (body) cues.push({ start: srtTime(a), end: srtTime(b), text: body });
  }
  return cues;
}

export async function GET(req: NextRequest) {
  const filePath = req.nextUrl.searchParams.get("path");
  if (!filePath) return NextResponse.json({ error: "Missing path" }, { status: 400 });
  if (filePath.split("/").includes("..")) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  if (path.basename(filePath) !== "captions.srt") {
    return NextResponse.json({ error: "Only captions.srt is served" }, { status: 415 });
  }
  try {
    const cues = parseSrt(fs.readFileSync(filePath, "utf-8"));
    dlog("producer:transcript", "read", { file: filePath, cues: cues.length });
    return NextResponse.json({ available: true, cues });
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT") {
      return NextResponse.json(
        { available: false, error: "This render does not have a caption transcript yet." },
        { status: 404 },
      );
    }
    dlog("producer:transcript", "read failed", {
      file: filePath,
      error: error instanceof Error ? error.message : String(error),
    });
    return NextResponse.json(
      { error: "The caption transcript could not be read. Try again or re-render the video." },
      { status: 500 },
    );
  }
}
