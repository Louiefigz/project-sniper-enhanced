import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { linkSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { cutMediaRange, cutMediaResponse } from "@/app/api/producer/cut-review/media";
import { GET } from "@/app/api/producer/cut-review/route";
import { GET as videoGet } from "@/app/api/producer/cut-review/video/route";

async function fixture(run: (file: string, bytes: Buffer) => Promise<void>) {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-cut-review-media-")));
  const bytes = Buffer.alloc(800_000, 65), file = path.join(directory, "cut-preview.mp4");
  writeFileSync(file, bytes);
  try { await run(file, bytes); } finally { rmSync(directory, { force: true, recursive: true }); }
}
function binding(file: string, bytes: Buffer) {
  return { path: file, sha256: createHash("sha256").update(bytes).digest("hex"), sizeBytes: bytes.length };
}
function request(range?: string, method = "GET") {
  return new Request("http://localhost/api/producer/cut-review/video", { method,
    headers: range ? { Range: range } : undefined });
}

test("range parser rejects ambiguous/unsafe ranges and supports browser suffixes", () => {
  assert.deepEqual(cutMediaRange(null, 100), [0, 99]);
  assert.deepEqual(cutMediaRange("bytes=3-8", 100), [3, 8]);
  assert.deepEqual(cutMediaRange("bytes=99-999", 100), [99, 99]);
  assert.deepEqual(cutMediaRange("bytes=-5", 100), [95, 99]);
  assert.deepEqual(cutMediaRange("bytes=-1000", 100), [0, 99]);
  for (const range of ["bytes=-", "bytes=-0", "bytes=100-", "bytes=8-3", "bytes=0-1,3-4",
    "bytes=1.5-", "other=0-1", "bytes=9007199254740993-", "bytes=0-1 trailing"]) {
    assert.equal(cutMediaRange(range, 100), null, range);
  }
});

test("whole/range/HEAD responses serve only the exact hashed descriptor", async () => fixture(async (file, bytes) => {
  const whole = await cutMediaResponse(request(), binding(file, bytes));
  assert.equal(whole.status, 200);
  assert.deepEqual(Buffer.from(await whole.arrayBuffer()), bytes);
  const partial = await cutMediaResponse(request("bytes=7-18"), binding(file, bytes));
  assert.equal(partial.status, 206); assert.equal(partial.headers.get("content-range"), "bytes 7-18/800000");
  assert.deepEqual(Buffer.from(await partial.arrayBuffer()), bytes.subarray(7, 19));
  assert.equal(partial.headers.get("cross-origin-resource-policy"), "same-origin");
  assert.equal(partial.headers.get("cache-control"), "private, no-store");
  const head = await cutMediaResponse(request(undefined, "HEAD"), binding(file, bytes));
  assert.equal(head.headers.get("content-length"), "800000"); assert.equal(await head.text(), "");
  const invalid = await cutMediaResponse(request("bytes=999999-"), binding(file, bytes));
  assert.equal(invalid.status, 416); assert.equal(invalid.headers.get("content-range"), "bytes */800000");
}));

test("changed hashes, hardlinks, symlinks and canceled reads cannot yield playback", async () => fixture(async (file, bytes) => {
  await assert.rejects(cutMediaResponse(request(), { ...binding(file, bytes), sha256: "0".repeat(64) }), /differ/);
  const alias = `${file}.alias`;
  symlinkSync(file, alias);
  await assert.rejects(cutMediaResponse(request(), binding(alias, bytes)));
  rmSync(alias); linkSync(file, alias);
  await assert.rejects(cutMediaResponse(request(), binding(file, bytes)), /bounded/);
  rmSync(alias);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(cutMediaResponse(new Request("http://localhost", { signal: controller.signal }), binding(file, bytes)));
}));

test("HEAD and short ranges still detect corruption outside the requested range", async () => fixture(async (file, bytes) => {
  const expected = binding(file, bytes);
  const changed = Buffer.from(bytes); changed[changed.length - 1] = 99;
  writeFileSync(file, changed);
  await assert.rejects(cutMediaResponse(request("bytes=0-10"), expected), /differ/);
  await assert.rejects(cutMediaResponse(request(undefined, "HEAD"), expected), /differ/);
}));

test("same-size mutation during playback aborts the remaining stream", async () => fixture(async (file, bytes) => {
  const response = await cutMediaResponse(request(), binding(file, bytes));
  const reader = response.body!.getReader();
  const first = await reader.read(); assert.equal(first.done, false);
  writeFileSync(file, Buffer.alloc(bytes.length, 66));
  await assert.rejects(async () => { while (!(await reader.read()).done) { /* consume until the checked stream aborts */ } }, /changed/);
}));

test("request abort after verification rejects playback even when the reader is idle", async () => fixture(async (file, bytes) => {
  const controller = new AbortController();
  const response = await cutMediaResponse(new Request("http://localhost", { signal: controller.signal }), binding(file, bytes));
  controller.abort(new Error("playback canceled"));
  await assert.rejects(response.arrayBuffer(), /canceled|closed|abort/i);
}));

test("review routes reject cross-origin, arbitrary paths and duplicate identities before reads", async () => {
  for (const route of [GET, videoGet]) {
    const cross = await route(new NextRequest("http://localhost/api/producer/cut-review", {
      headers: { host: "localhost", origin: "https://untrusted.example", "sec-fetch-site": "cross-site" } }));
    assert.equal(cross.status, 403);
    const extra = await route(new NextRequest("http://localhost/api/producer/cut-review?dir=/private/tmp&path=/tmp/file.mp4", {
      headers: { host: "localhost" } }));
    assert.equal(extra.status, 400);
    const duplicate = await route(new NextRequest("http://localhost/api/producer/cut-review?dir=/a&dir=/b", {
      headers: { host: "localhost" } }));
    assert.equal(duplicate.status, 400);
  }
});
