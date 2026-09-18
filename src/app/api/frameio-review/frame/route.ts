import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import os from "os";
import path from "path";

// Serves a single extracted thumbnail JPG from the producer's temp dir.
// review.py writes frames to <tmp>/frameio-<token>/frame_*.jpg; we only serve
// files under that exact prefix, ending in .jpg, with no traversal — so this
// can't be used as a generic local-file read primitive.
export async function GET(req: NextRequest) {
  const p = req.nextUrl.searchParams.get("path");
  if (!p) return new NextResponse("Missing path", { status: 400 });

  const resolved = path.resolve(p);
  const allowedRoot = path.join(os.tmpdir(), "frameio-");
  const isFrameDir =
    resolved.startsWith(allowedRoot) ||
    // os.tmpdir() can differ from the python tempfile dir symlink-wise (/var vs
    // /private/var on macOS); also accept the realpath form.
    resolved.startsWith(path.join("/private", allowedRoot));

  if (!isFrameDir || !resolved.endsWith(".jpg")) {
    return new NextResponse("Forbidden", { status: 403 });
  }

  let buf: Buffer;
  try {
    buf = fs.readFileSync(resolved);
  } catch {
    return new NextResponse("Not found", { status: 404 });
  }

  return new NextResponse(new Uint8Array(buf), {
    status: 200,
    headers: { "Content-Type": "image/jpeg", "Cache-Control": "no-store" },
  });
}
