import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import os from "os";
import path from "path";
import crypto from "crypto";
import { runCmd } from "../../_lib/run-cmd";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// A horizontal thumbnail sprite for the timeline video lane. ffmpeg samples N
// evenly-spaced frames and tiles them 1×N; cached under tmp by (path, mtime, n)
// so it's generated once. Locked to .mp4 by absolute path (traversal-guarded).
// n caps at 160 (≈15k sprite px) — the timeline's zoom quantizes its requests
// (timeline-scale.filmstripCols) and stretches beyond the cap rather than
// generating unbounded sprites; whole-video tiling is the deliberate contract.
export async function GET(req: NextRequest) {
  const filePath = req.nextUrl.searchParams.get("path");
  const n = Math.min(160, Math.max(8, parseInt(req.nextUrl.searchParams.get("n") || "40", 10)));
  if (!filePath) return new NextResponse("Missing path", { status: 400 });
  if (filePath.split("/").includes("..") || path.extname(filePath).toLowerCase() !== ".mp4") {
    return new NextResponse("Forbidden", { status: 403 });
  }
  let stat: fs.Stats;
  try {
    stat = fs.statSync(filePath);
  } catch {
    return new NextResponse("Not found", { status: 404 });
  }

  const key = crypto.createHash("sha1").update(`${filePath}:${stat.mtimeMs}:${n}`).digest("hex").slice(0, 16);
  const sprite = path.join(os.tmpdir(), `producer-strip-${key}.png`);

  if (!fs.existsSync(sprite)) {
    const probe = await runCmd("ffprobe", [
      "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", filePath,
    ]);
    const dur = parseFloat(probe.stdout.toString().trim() || "0");
    if (!dur) return new NextResponse("Cannot probe duration", { status: 500 });
    const fps = (n / dur).toFixed(6);
    const gen = await runCmd("ffmpeg", [
      "-hide_banner", "-loglevel", "error", "-i", filePath,
      "-vf", `fps=${fps},scale=96:54:force_original_aspect_ratio=increase,crop=96:54,tile=${n}x1`,
      "-frames:v", "1", "-y", sprite,
    ]);
    if (gen.status !== 0 || !fs.existsSync(sprite)) {
      return new NextResponse(`ffmpeg failed: ${gen.stderr.toString().slice(-200)}`, { status: 500 });
    }
    dlog("producer:filmstrip", "generated", { file: filePath, n, sprite });
  }

  return new NextResponse(new Uint8Array(fs.readFileSync(sprite)), {
    status: 200,
    headers: { "Content-Type": "image/png", "Cache-Control": "no-store", "X-Strip-Cols": String(n) },
  });
}
