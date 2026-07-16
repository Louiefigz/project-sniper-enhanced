import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { dlog } from "@/lib/debug";

const MIME_TYPES: Record<string, string> = {
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".webm": "video/webm",
  ".mkv": "video/x-matroska",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".aac": "audio/aac",
  ".wav": "audio/wav",
  ".flac": "audio/flac",
  ".ogg": "audio/ogg",
  ".opus": "audio/opus",
};

export async function GET(req: NextRequest) {
  const filePath = req.nextUrl.searchParams.get("path");
  if (!filePath) {
    return new NextResponse("Missing path", { status: 400 });
  }

  // Reject path-traversal segments before any filesystem call. The legitimate
  // caller is the native picker, which always returns absolute paths.
  if (filePath.split("/").includes("..")) {
    return new NextResponse("Forbidden", { status: 403 });
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext];
  if (!contentType) {
    // Only allowlisted media extensions are served — prevents using this route
    // as a generic file-read primitive (e.g. /etc/passwd) from any local browser.
    return new NextResponse("Unsupported media type", { status: 415 });
  }

  let stat: fs.Stats;
  try {
    stat = fs.statSync(filePath);
  } catch {
    return new NextResponse("File not found", { status: 404 });
  }

  if (!stat.isFile()) {
    return new NextResponse("Not a file", { status: 400 });
  }

  const fileSize = stat.size;
  const rangeHeader = req.headers.get("range");

  // Log the opening request (full file / first byte range) — skip mid-scrub
  // ranges to avoid flooding the console during playback.
  if (!rangeHeader || /bytes=0-/.test(rangeHeader)) {
    dlog("clipper:video", "serve", { file: filePath.split("/").pop(), contentType, sizeMB: +(fileSize / 1048576).toFixed(1), range: rangeHeader ?? "full" });
  }

  if (rangeHeader) {
    const match = rangeHeader.match(/bytes=(\d+)-(\d*)/);
    if (!match) {
      return new NextResponse("Invalid range", { status: 416 });
    }
    const start = parseInt(match[1], 10);
    const requestedEnd = match[2] ? parseInt(match[2], 10) : fileSize - 1;

    // Reject ranges that start past EOF or invert (e.g. "bytes=5000-100"), which
    // would otherwise yield a negative Content-Length and a broken stream.
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
