import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { dlog } from "@/lib/debug";

// Streams the locally-picked MP4 to the in-tab player with HTTP range support.
// Same local-only contract as CLIPPER's api/clipper/video — nothing is uploaded.
const MIME_TYPES: Record<string, string> = {
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".webm": "video/webm",
  ".mkv": "video/x-matroska",
  ".m4v": "video/x-m4v",
};

export async function GET(req: NextRequest) {
  const filePath = req.nextUrl.searchParams.get("path");
  if (!filePath) return new NextResponse("Missing path", { status: 400 });
  if (filePath.split("/").includes("..")) return new NextResponse("Forbidden", { status: 403 });

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext];
  if (!contentType) return new NextResponse("Unsupported media type", { status: 415 });

  let stat: fs.Stats;
  try {
    stat = fs.statSync(filePath);
  } catch {
    return new NextResponse("File not found", { status: 404 });
  }
  if (!stat.isFile()) return new NextResponse("Not a file", { status: 400 });

  const fileSize = stat.size;
  const rangeHeader = req.headers.get("range");
  if (!rangeHeader || /bytes=0-/.test(rangeHeader)) {
    dlog("frameio:video", "serve", {
      file: filePath.split("/").pop(),
      sizeMB: +(fileSize / 1048576).toFixed(1),
      range: rangeHeader ?? "full",
    });
  }

  if (rangeHeader) {
    const match = rangeHeader.match(/bytes=(\d+)-(\d*)/);
    if (!match) return new NextResponse("Invalid range", { status: 416 });
    const start = parseInt(match[1], 10);
    const requestedEnd = match[2] ? parseInt(match[2], 10) : fileSize - 1;
    if (start >= fileSize || start > requestedEnd) {
      return new NextResponse("Range Not Satisfiable", {
        status: 416,
        headers: { "Content-Range": `bytes */${fileSize}` },
      });
    }
    const end = Math.min(requestedEnd, fileSize - 1);
    const chunkSize = end - start + 1;
    const stream = fs.createReadStream(filePath, { start, end });
    const webStream = new ReadableStream({
      start(controller) {
        stream.on("data", (chunk) => controller.enqueue(chunk));
        stream.on("end", () => controller.close());
        stream.on("error", (err) => controller.error(err));
      },
      cancel() { stream.destroy(); },
    });
    return new NextResponse(webStream, {
      status: 206,
      headers: {
        "Content-Type": contentType,
        "Content-Range": `bytes ${start}-${end}/${fileSize}`,
        "Accept-Ranges": "bytes",
        "Content-Length": String(chunkSize),
      },
    });
  }

  const stream = fs.createReadStream(filePath);
  const webStream = new ReadableStream({
    start(controller) {
      stream.on("data", (chunk) => controller.enqueue(chunk));
      stream.on("end", () => controller.close());
      stream.on("error", (err) => controller.error(err));
    },
    cancel() { stream.destroy(); },
  });
  return new NextResponse(webStream, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Accept-Ranges": "bytes",
      "Content-Length": String(fileSize),
    },
  });
}
