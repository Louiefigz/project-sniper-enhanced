import { NextRequest, NextResponse } from "next/server";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { Readable } from "node:stream";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { OPENING_RANGES, readSelectedOpeningMedia, type OpeningRange } from "@/lib/server/guided-opening-selection";
import { canonicalProducerDir } from "../../auto-edit/request";

export const dynamic = "force-dynamic";
export const maxDuration = 60;
const HEADERS = { "Cache-Control": "private, no-store", "Accept-Ranges": "bytes", "Content-Type": "video/mp4" };
const KEYS = ["dir", "selectionHash", "mediaSha256", "range"], HASH = /^[0-9a-f]{64}$/, CHUNK = 4 * 1024 * 1024;

function rejected(message: string, status: number) {
  return NextResponse.json({ ok: false, error: message }, { status, headers: { "Cache-Control": "private, no-store" } });
}

/** Whole-file SHA-256 through the SAME descriptor the range is served from; no path input, no per-seek source decode. */
function hashDescriptor(fd: number, size: number): string {
  const hash = createHash("sha256"), buffer = Buffer.alloc(Math.min(CHUNK, size));
  let offset = 0;
  while (offset < size) {
    const read = fs.readSync(fd, buffer, 0, Math.min(buffer.length, size - offset), offset);
    if (read <= 0) throw new Error("Opening media ended before its selected size");
    hash.update(buffer.subarray(0, read)); offset += read;
  }
  return hash.digest("hex");
}

function parseRange(header: string | null, size: number): { start: number; end: number } | null | "invalid" {
  if (!header) return null;
  const match = /^bytes=(\d+)-(\d*)$/.exec(header);
  if (!match) return "invalid";
  const start = Number(match[1]), end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  if (!Number.isSafeInteger(start) || start >= size || start > end) return "invalid";
  return { start, end };
}

/** Local read-only playback of the exact selected private range artifact. Never approval, never an arbitrary file read. */
export async function GET(req: NextRequest): Promise<Response> {
  const denied = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname, protocol: req.nextUrl.protocol,
    host: req.headers.get("host"), origin: req.headers.get("origin"), secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type") });
  if (denied) return rejected(denied.error, denied.status);
  const query = req.nextUrl.searchParams, keys = [...query.keys()];
  if (req.nextUrl.search.length > 8192 || keys.length !== 4 || KEYS.some((key) => query.getAll(key).length !== 1)
      || !HASH.test(query.get("selectionHash") ?? "") || !HASH.test(query.get("mediaSha256") ?? "")
      || !OPENING_RANGES.includes(query.get("range") as OpeningRange) || !query.get("dir") || query.get("dir")!.length > 4096) {
    return rejected("Opening media requires exactly dir, selectionHash, mediaSha256 and range", 400);
  }
  let row: { path: string; mediaSha256: string; sizeBytes: number };
  try {
    const selected = readSelectedOpeningMedia(canonicalProducerDir(query.get("dir")));
    if (selected.selectionHash !== query.get("selectionHash")) return rejected("Opening selection is not current", 409);
    row = selected.rows[query.get("range") as OpeningRange];
    if (row.mediaSha256 !== query.get("mediaSha256")) return rejected("Opening media identity is not the selected artifact", 409);
  } catch { return rejected("Current opening selection could not be verified; no media is selectable", 409); }
  let fd: number;
  try { fd = fs.openSync(row.path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW); }
  catch { return rejected("Opening selected media is unavailable", 409); }
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size !== row.sizeBytes || hashDescriptor(fd, stat.size) !== row.mediaSha256) { fs.closeSync(fd); return rejected("Opening selected media bytes changed", 409); }
    const range = parseRange(req.headers.get("range"), stat.size);
    if (range === "invalid") { fs.closeSync(fd); return new NextResponse(null, { status: 416, headers: { ...HEADERS, "Content-Range": `bytes */${stat.size}` } }); }
    const start = range?.start ?? 0, end = range?.end ?? stat.size - 1;
    const stream = fs.createReadStream("", { fd, start, end, autoClose: true });
    return new NextResponse(Readable.toWeb(stream) as ReadableStream, { status: range ? 206 : 200,
      headers: { ...HEADERS, "Content-Length": String(end - start + 1), ...(range ? { "Content-Range": `bytes ${start}-${end}/${stat.size}` } : {}) } });
  } catch { fs.closeSync(fd); return rejected("Opening selected media could not be served", 409); }
}
