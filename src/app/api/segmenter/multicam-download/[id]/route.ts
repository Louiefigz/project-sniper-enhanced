import { NextResponse } from "next/server";
import { createReadStream, existsSync, statSync, unlinkSync } from "fs";
import { Readable } from "stream";
import { take } from "../../../_lib/multicam-store";
import { dlog } from "@/lib/debug";

export const runtime = "nodejs";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  dlog("segmenter:multicam", "download requested", { id });
  const entry = take(id);
  if (!entry || !existsSync(entry.zipPath)) {
    dlog("segmenter:multicam", "download not found or expired", { id });
    return NextResponse.json({ error: "Download not found or expired" }, { status: 404 });
  }

  const size = statSync(entry.zipPath).size;
  dlog("segmenter:multicam", "download sending zip", { id, filename: entry.filename, sizeBytes: size });
  const nodeStream = createReadStream(entry.zipPath);
  nodeStream.on("close", () => {
    dlog("segmenter:multicam", "download sent, deleting zip", { id, zipPath: entry.zipPath });
    try { unlinkSync(entry.zipPath); } catch {}
  });
  const webStream = Readable.toWeb(nodeStream) as unknown as ReadableStream<Uint8Array>;

  return new NextResponse(webStream, {
    headers: {
      "Content-Type": "application/zip",
      "Content-Length": String(size),
      "Content-Disposition": `attachment; filename="${entry.filename}"`,
    },
  });
}
