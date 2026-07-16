import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { runCmd } from "../../_lib/run-cmd";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// Downsampled audio peaks (0..1) for the timeline waveform lane. ffmpeg decodes
// the track to mono 4kHz s16le; we bucket it into `buckets` max-abs peaks.
// Locked to .mp4/.wav/.m4a by absolute path (traversal-guarded).
const OK_EXT = new Set([".mp4", ".mov", ".wav", ".m4a", ".mp3"]);

export async function GET(req: NextRequest) {
  const filePath = req.nextUrl.searchParams.get("path");
  const buckets = Math.min(2000, Math.max(100, parseInt(req.nextUrl.searchParams.get("buckets") || "600", 10)));
  if (!filePath) return NextResponse.json({ error: "Missing path" }, { status: 400 });
  if (filePath.split("/").includes("..") || !OK_EXT.has(path.extname(filePath).toLowerCase())) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  try {
    fs.statSync(filePath);
  } catch {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const out = await runCmd(
    "ffmpeg",
    ["-hide_banner", "-loglevel", "error", "-i", filePath,
     "-ac", "1", "-ar", "4000", "-f", "s16le", "-acodec", "pcm_s16le", "-"],
  );
  if (out.status !== 0 || !out.stdout.length) {
    return NextResponse.json({ peaks: [] }); // no audio / decode fail → empty (lane hides)
  }
  const pcm = new Int16Array(
    out.stdout.buffer.slice(out.stdout.byteOffset, out.stdout.byteOffset + out.stdout.length),
  );
  const per = Math.max(1, Math.floor(pcm.length / buckets));
  const peaks: number[] = [];
  for (let i = 0; i < pcm.length; i += per) {
    let max = 0;
    for (let j = i; j < i + per && j < pcm.length; j++) {
      const a = Math.abs(pcm[j]);
      if (a > max) max = a;
    }
    peaks.push(+(max / 32768).toFixed(3));
  }
  dlog("producer:waveform", "peaks", { file: filePath, samples: pcm.length, buckets: peaks.length });
  return NextResponse.json({ peaks }, { headers: { "Cache-Control": "no-store" } });
}
