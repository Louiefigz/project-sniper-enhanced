import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import os from "os";
import path from "path";
import crypto from "crypto";
import { runCmd } from "../../_lib/run-cmd";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// One SOURCE-frame JPEG for the crop modal: GET ?dir=&t=<sourceSeconds>
// [&sourceId=<manifest source id>]. Path guard (same shape as words/route.ts):
// the video path is DERIVED from <dir>/base.fingerprint.json (fixed basename)
// → manifestPath → the matching manifest.sources[].path (default sources[0]) —
// the query never names an arbitrary file, so this is not a generic local-file
// read primitive. Frames are cached in tmp by sha1(path:mtime:t rounded to
// 0.1s); dims (ffprobe) are cached in-memory and returned as the
// X-Source-Dims header ("WxH", DISPLAY-oriented — see probeDims).

const dimsCache = new Map<string, string>(); // `${path}:${mtimeMs}` -> "WxH"

/** Caller error (bad query param) — mapped to HTTP 400, not 500. */
class BadRequestError extends Error {}

function readJson(file: string): unknown {
  return JSON.parse(fs.readFileSync(file, "utf-8"));
}

/**
 * <dir>/base.fingerprint.json → manifestPath → the source's path (absolute).
 * `sourceId` must match a manifest source id (400 otherwise); null = sources[0].
 */
function resolveSourcePath(dir: string, sourceId: string | null): string {
  const fp = readJson(path.join(dir, "base.fingerprint.json")) as { manifestPath?: string };
  if (!fp.manifestPath) throw new Error("base.fingerprint.json has no manifestPath");
  const manifest = readJson(fp.manifestPath) as { sources?: { id?: string; path?: string }[] };
  const sources = manifest.sources ?? [];
  const entry = sourceId ? sources.find((s) => s.id === sourceId) : sources[0];
  if (sourceId && !entry) {
    const known = sources.map((s) => s.id).join(", ") || "none";
    throw new BadRequestError(`sourceId ${sourceId} not in manifest sources (known: ${known})`);
  }
  const src = entry?.path;
  if (!src) throw new Error(`${fp.manifestPath}: no path for source ${sourceId ?? "[0]"}`);
  return path.resolve(path.dirname(fp.manifestPath), src);
}

interface ProbeStream {
  width?: number;
  height?: number;
  side_data_list?: { rotation?: number | string }[];
}

/** True when a display-matrix rotation makes the file display sideways (±90/±270). */
function isRotated(stream: ProbeStream): boolean {
  return (stream.side_data_list ?? []).some(
    (side) => Math.abs(Math.trunc(Number(side?.rotation ?? 0))) % 180 === 90,
  );
}

/**
 * DISPLAY-oriented "WxH" — mirrors cut_speed.py display_dims (edge I9): phone
 * footage stores landscape coded pixels + a display-matrix rotation flag, and
 * ffmpeg autorotates the extracted JPEG, so the header must swap w/h on
 * ±90/±270 to match what the modal actually shows.
 */
async function probeDims(file: string, mtimeMs: number): Promise<string> {
  const key = `${file}:${mtimeMs}`;
  const hit = dimsCache.get(key);
  if (hit) return hit;
  const probe = await runCmd("ffprobe", [
    "-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=width,height:stream_side_data=rotation",
    "-of", "json", file,
  ]);
  let stream: ProbeStream | undefined;
  try {
    stream = (JSON.parse(probe.stdout.toString()) as { streams?: ProbeStream[] }).streams?.[0];
  } catch {
    stream = undefined;
  }
  const w = stream?.width;
  const h = stream?.height;
  if (probe.status !== 0 || !stream || !Number.isInteger(w) || !Number.isInteger(h) || !w || !h) {
    throw new Error(`ffprobe could not read dimensions of ${file}`);
  }
  const dims = isRotated(stream) ? `${h}x${w}` : `${w}x${h}`;
  dimsCache.set(key, dims);
  return dims;
}

/** Extract ONE frame at t (already rounded) to the cache path, or throw. */
async function extractFrame(src: string, t: number, jpg: string): Promise<void> {
  const gen = await runCmd("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-ss", String(t), "-i", src, "-frames:v", "1", "-q:v", "3", "-y", jpg,
  ]);
  const noFrame = gen.status !== 0 || !fs.existsSync(jpg) || fs.statSync(jpg).size === 0;
  if (noFrame) {
    if (fs.existsSync(jpg)) fs.unlinkSync(jpg); // never cache an empty jpeg
    const tail = gen.stderr.toString().slice(-300) || "no frame produced (t past EOF?)";
    throw new Error(`ffmpeg failed at t=${t}: ${tail}`);
  }
}

export async function GET(req: NextRequest) {
  const dir = (req.nextUrl.searchParams.get("dir") || "").replace(/\/$/, "");
  if (!dir) return NextResponse.json({ error: "Missing dir" }, { status: 400 });
  if (dir.split("/").includes("..")) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  const t = parseFloat(req.nextUrl.searchParams.get("t") || "");
  if (!Number.isFinite(t) || t < 0) {
    return NextResponse.json({ error: "t must be a finite number >= 0" }, { status: 400 });
  }
  if (!fs.existsSync(path.join(dir, "base.fingerprint.json"))) {
    return NextResponse.json(
      { error: `No base.fingerprint.json in ${dir} — source frames are only served for a rendered base` },
      { status: 409 },
    );
  }

  const sourceId = req.nextUrl.searchParams.get("sourceId");

  try {
    const src = resolveSourcePath(dir, sourceId);
    if (!fs.existsSync(src)) {
      return NextResponse.json({ error: `Source video not found: ${src}` }, { status: 404 });
    }
    const mtimeMs = fs.statSync(src).mtimeMs;
    const tR = Math.round(t * 10) / 10; // 0.1s cache grid
    const key = crypto.createHash("sha1").update(`${src}:${mtimeMs}:${tR}`).digest("hex").slice(0, 16);
    const jpg = path.join(os.tmpdir(), `producer-srcframe-${key}.jpg`);
    const dims = await probeDims(src, mtimeMs);
    if (!fs.existsSync(jpg)) {
      await extractFrame(src, tR, jpg);
      dlog("producer:source-frame", "extracted", { src, t: tR, jpg });
    }
    return new NextResponse(new Uint8Array(fs.readFileSync(jpg)), {
      status: 200,
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "no-store",
        "X-Source-Dims": dims,
      },
    });
  } catch (e) {
    const status = e instanceof BadRequestError ? 400 : 500;
    return NextResponse.json({ error: (e as Error).message }, { status });
  }
}
