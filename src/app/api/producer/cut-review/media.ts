import { constants, type BigIntStats } from "node:fs";
import { lstat, open, realpath, type FileHandle } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { CutReviewError } from "./state";

const MAXIMUM = 2 * 1024 ** 3;
const CHUNK = 256 * 1024;
const STAMP_KEYS = ["dev", "ino", "size", "mtimeNs", "ctimeNs", "nlink"] as const;
interface Binding { path: string; sha256: string; sizeBytes: number }
interface Opened { handle: FileHandle; check: () => Promise<void>; size: number }

function sameStamp(before: BigIntStats, after: BigIntStats): boolean {
  return STAMP_KEYS.every((key) => before[key] === after[key]);
}

/** Closed single-range support, including browser suffix requests; no multipart body. */
export function cutMediaRange(header: string | null, size: number): [number, number] | null {
  if (!header) return [0, size - 1];
  const match = /^bytes=(\d*)-(\d*)$/.exec(header);
  if (!match || (!match[1] && !match[2])) return null;
  const left = match[1] ? Number(match[1]) : null;
  const right = match[2] ? Number(match[2]) : null;
  if ([left, right].some((value) => value !== null && (!Number.isSafeInteger(value) || value < 0))) return null;
  if (left === null) return right ? [Math.max(0, size - right), size - 1] : null;
  if (left >= size || (right !== null && right < left)) return null;
  return [left, Math.min(right ?? size - 1, size - 1)];
}

async function openedMedia(binding: Binding): Promise<Opened> {
  const parent = path.dirname(binding.path);
  if (await realpath(parent) !== parent) throw new CutReviewError("Private preview directory is no longer canonical");
  const parentStamp = await lstat(parent, { bigint: true });
  const handle = await open(binding.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await handle.stat({ bigint: true });
    if (!before.isFile() || before.nlink !== BigInt(1) || before.size !== BigInt(binding.sizeBytes)
        || binding.sizeBytes < 1 || binding.sizeBytes > MAXIMUM || !/^[a-f0-9]{64}$/.test(binding.sha256)) {
      throw new CutReviewError("Private preview is not the bounded receipt-bound media file");
    }
    const check = async () => {
      const [opened, current, directory] = await Promise.all([handle.stat({ bigint: true }),
        lstat(binding.path, { bigint: true }), lstat(parent, { bigint: true })]);
      if (!sameStamp(before, opened) || !sameStamp(before, current) || current.isSymbolicLink()
          || directory.dev !== parentStamp.dev || directory.ino !== parentStamp.ino
          || directory.isSymbolicLink() || await realpath(parent) !== parent) {
        throw new CutReviewError("Private preview changed while being served");
      }
    };
    await check();
    return { handle, check, size: binding.sizeBytes };
  } catch (error) { await handle.close(); throw error; }
}

async function verifyBytes(opened: Opened, expected: string, signal: AbortSignal): Promise<void> {
  const digest = createHash("sha256"), buffer = Buffer.alloc(CHUNK);
  const deadline = performance.now() + 30_000;
  for (let offset = 0; offset < opened.size;) {
    signal.throwIfAborted();
    if (performance.now() > deadline) throw new CutReviewError("Private preview verification exceeded its 30-second read deadline");
    const { bytesRead } = await opened.handle.read(buffer, 0, Math.min(buffer.length, opened.size - offset), offset);
    if (!bytesRead) throw new CutReviewError("Private preview was truncated during verification");
    digest.update(buffer.subarray(0, bytesRead)); offset += bytesRead;
  }
  await opened.check();
  if (digest.digest("hex") !== expected) throw new CutReviewError("Private preview bytes differ from their receipt");
}

function mediaStream(opened: Opened, range: [number, number], signal: AbortSignal): ReadableStream<Uint8Array> {
  let offset = range[0], closed = false;
  let removeAbort = () => {};
  const close = async () => { if (!closed) { closed = true; removeAbort(); await opened.handle.close(); } };
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const aborted = () => { void close().then(() => controller.error(signal.reason), (error) => controller.error(error)); };
      removeAbort = () => signal.removeEventListener("abort", aborted);
      signal.addEventListener("abort", aborted, { once: true });
      if (signal.aborted) aborted();
    },
    async pull(controller) {
      try {
        signal.throwIfAborted(); await opened.check();
        const buffer = Buffer.alloc(Math.min(CHUNK, range[1] - offset + 1));
        const { bytesRead } = await opened.handle.read(buffer, 0, buffer.length, offset);
        if (!bytesRead) throw new CutReviewError("Private preview truncated during playback");
        await opened.check();
        offset += bytesRead; controller.enqueue(buffer.subarray(0, bytesRead));
        if (offset > range[1]) { await close(); controller.close(); }
      } catch (error) { await close(); controller.error(error); }
    },
    cancel: close,
  });
}

/** Hash and stream the same descriptor; no path reopen or unchecked range shortcut. */
export async function cutMediaResponse(req: Request, binding: Binding): Promise<Response> {
  const opened = await openedMedia(binding);
  try {
    await verifyBytes(opened, binding.sha256, req.signal);
    const headers = new Headers({ "Content-Type": "video/mp4", "Cache-Control": "private, no-store",
      "Cross-Origin-Resource-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
      "Accept-Ranges": "bytes", ETag: `"${binding.sha256}"` });
    const range = cutMediaRange(req.headers.get("range"), opened.size);
    if (!range) {
      await opened.handle.close(); headers.set("Content-Range", `bytes */${opened.size}`);
      return new Response(null, { status: 416, headers });
    }
    headers.set("Content-Length", String(range[1] - range[0] + 1));
    const partial = req.headers.has("range");
    if (partial) headers.set("Content-Range", `bytes ${range[0]}-${range[1]}/${opened.size}`);
    if (req.method === "HEAD") {
      await opened.handle.close(); return new Response(null, { status: partial ? 206 : 200, headers });
    }
    return new Response(mediaStream(opened, range, req.signal), { status: partial ? 206 : 200, headers });
  } catch (error) { await opened.handle.close().catch(() => {}); throw error; }
}
