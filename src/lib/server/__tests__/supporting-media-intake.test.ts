/** Real local copy/lease/request tests; sandbox decoding and ASR are not invoked. */
import assert from "node:assert/strict";
import { existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { ingestInto } from "@/components/producer/stage-ingest";
import { POST } from "@/app/api/producer/supporting-media/route";
import { ingestArguments, parseRequest } from "@/app/api/producer/ingest/request";
import { copyStableSource, stableCopySource } from "@/app/api/producer/ingest/source-copy";
import { stageSupportingMedia } from "../supporting-media-intake";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { nativeShortAppFixture } from "./_native-short-app-fixture";

function request(body: unknown, origin = "http://127.0.0.1:3327") {
  return new NextRequest("http://127.0.0.1:3327/api/producer/supporting-media", { method: "POST",
    headers: { host: "127.0.0.1:3327", origin, "content-type": "application/json" }, body: JSON.stringify(body) });
}

function fixture() {
  const f = nativeShortAppFixture(); rmSync(f.jobPath);
  return { ...f, broll: path.join(f.root, "source/broll"), signal: new AbortController().signal };
}

test("picked image is copied exclusively with source provenance and no manifest mutation", async () => {
  const f = fixture(), before = readFileSync(f.manifestPath);
  try {
    mkdirSync(f.broll); const existing = path.join(f.broll, path.basename(f.picture)); writeFileSync(existing, "existing image");
    const response = await POST(request({ dir: f.dir, inputPath: f.picture })), result = await response.json();
    assert.equal(response.status, 200, JSON.stringify(result));
    assert.equal(result.status, "staged-awaiting-sandbox-admission"); assert.equal(result.providerCalls, 0);
    assert.deepEqual(readFileSync(result.path), readFileSync(f.picture));
    assert.deepEqual(readFileSync(f.manifestPath), before); assert.equal(readFileSync(existing, "utf8"), "existing image");
    const receipt = JSON.parse(readFileSync(path.join(path.dirname(result.path), ".sniper-supplied.json"), "utf8"));
    assert.equal(receipt.originalPath, f.picture); assert.equal(receipt.sha256, result.sha256);
    assert.equal(readdirSync(f.broll).some(name => name.startsWith(".")), false);
  } finally { f.cleanup(); }
});

test("failed or canceled copy leaves no ingestible partial file and releases the lease", async () => {
  const f = fixture();
  try {
    await assert.rejects(() => stageSupportingMedia({ ...f, inputPath: f.picture }, { copy: async (_entry, destination) => {
      writeFileSync(destination, "partial"); throw new Error("TEST copy interrupted");
    } }), /copy interrupted/);
    assert.deepEqual(readdirSync(f.broll), []);
    const abort = new AbortController(); abort.abort();
    await assert.rejects(() => stageSupportingMedia({ ...f, inputPath: f.picture, signal: abort.signal }), /abort/i);
    const held = acquireProjectMutationLease(f.root, "TEST released"); assert.ok(held.lease); held.lease.release();
  } finally { f.cleanup(); }
});

test("video staging accepts MP4 and MOV without pretending they were decoded", async () => {
  const f = fixture();
  try {
    for (const suffix of [".mp4", ".mov"]) {
      const file = path.join(f.root, `cutaway${suffix}`); writeFileSync(file, "TEST synthetic video bytes");
      const response = await POST(request({ dir: f.dir, inputPath: file }));
      assert.equal(response.status, 200); assert.equal((await response.json()).status, "staged-awaiting-sandbox-admission");
    }
  } finally { f.cleanup(); }
});

test("unsupported documents, hidden files and symlink paths never become staged assets", async () => {
  const f = fixture();
  try {
    for (const name of ["logo.svg", "logo.svgz", "asset.gif", ".hidden.png"]) {
      const file = path.join(f.root, name); writeFileSync(file, "TEST rejected bytes");
      assert.equal((await POST(request({ dir: f.dir, inputPath: file }))).status, 400);
    }
    const alias = path.join(f.root, "alias.png"); symlinkSync(f.picture, alias);
    assert.equal((await POST(request({ dir: f.dir, inputPath: alias }))).status, 400);
    symlinkSync(path.dirname(f.picture), f.broll);
    assert.equal((await POST(request({ dir: f.dir, inputPath: f.picture }))).status, 400);
    assert.equal(readdirSync(path.dirname(f.picture)).some(name => name.startsWith("import-")), false);
  } finally { f.cleanup(); }
});

test("guided checkpoint and competing writer retain ordinary mutation authority", async () => {
  const guided = nativeShortAppFixture();
  try {
    assert.equal((await POST(request({ dir: guided.dir, inputPath: guided.picture }))).status, 409);
    assert.equal(existsSync(path.join(guided.root, "source/broll")), false);
  } finally { guided.cleanup(); }
  const f = fixture(), held = acquireProjectMutationLease(f.root, "TEST concurrent writer"); assert.ok(held.lease);
  try { assert.equal((await POST(request({ dir: f.dir, inputPath: f.picture }))).status, 409); }
  finally { held.lease.release(); f.cleanup(); }
});

test("foreign origins and submitted destination or checkpoint overrides cannot stage files", async () => {
  const f = fixture();
  try {
    assert.equal((await POST(request({ dir: f.dir, inputPath: f.picture }, "https://foreign.test"))).status, 403);
    for (const extra of [{ destination: f.root }, { checkpointVerification: {} }, { intent: {} }]) {
      assert.equal((await POST(request({ dir: f.dir, inputPath: f.picture, ...extra }))).status, 400);
    }
    assert.equal(existsSync(f.broll), false);
  } finally { f.cleanup(); }
});

test("explicit rescan request selects transcript reuse and refuses conflicting mode flags", async () => {
  const f = fixture();
  try {
    const parsed = await parseRequest(request({ inputPath: path.dirname(f.manifestPath), projectRoot: f.root, reuseTranscripts: true }));
    assert.ok(!(parsed instanceof Response));
    const args = ingestArguments({ script: "ingest.py", inputPath: parsed.inputPath, manifestPath: f.manifestPath, request: parsed });
    assert.ok(args.includes("--reuse-transcripts")); assert.ok(!args.includes("--no-transcribe"));
    for (const extra of [{ reuseTranscripts: "yes" }, { reuseTranscripts: true, noTranscribe: true }]) {
      const invalid = await parseRequest(request({ inputPath: f.root, ...extra }));
      assert.ok(invalid instanceof Response); assert.equal(invalid.status, 400);
    }
  } finally { f.cleanup(); }
});

test("a selected regular file replaced by a FIFO fails without waiting for a writer", async () => {
  const f = fixture();
  try {
    const entry = stableCopySource(f.picture, "provided.png", lstatSync(f.picture, { bigint: true }));
    rmSync(f.picture);
    const command = spawnSync("mkfifo", [f.picture], { timeout: 1000 }); assert.equal(command.status, 0);
    await assert.rejects(() => copyStableSource(entry, path.join(f.root, "copy.png"), () => {}, f.signal), /changed before copy/);
    assert.equal(existsSync(path.join(f.root, "copy.png")), false);
  } finally { f.cleanup(); }
});

test("throwing a live copy guard rejects the pipeline and cleans private staging", async () => {
  const f = fixture();
  try {
    writeFileSync(f.picture, Buffer.alloc(256 * 1024, 1));
    await assert.rejects(() => stageSupportingMedia({ ...f, inputPath: f.picture }, { copy: async (entry, destination, _guard, signal) => {
      await copyStableSource(entry, destination, () => { throw new Error("TEST lease changed during real copy"); }, signal);
    } }), /lease changed during real copy/);
    assert.deepEqual(readdirSync(f.broll), []);
    const held = acquireProjectMutationLease(f.root, "TEST released after live guard error"); assert.ok(held.lease); held.lease.release();
  } finally { f.cleanup(); }
});


test("client rescan sends explicit reuse while normal speech preparation keeps its event callback", async t => {
  const bodies: unknown[] = [], updates: unknown[] = [], events: unknown[] = [];
  t.mock.method(globalThis, "fetch", async (_url: unknown, options: RequestInit) => {
    bodies.push(JSON.parse(String(options.body)));
    return new Response('data: {"event":"manifest","manifestPath":"/project/source/asset_manifest.json","outDir":"/project/source","manifest":{"sources":[]}}\n\n',
      { headers: { "content-type": "text/event-stream" } });
  });
  await ingestInto("/project/source", "/project", value => updates.push(value), { reuseTranscripts: true });
  await ingestInto("/project/source", "/project", value => updates.push(value), value => events.push(value));
  assert.deepEqual(bodies, [{ inputPath: "/project/source", projectRoot: "/project", reuseTranscripts: true },
    { inputPath: "/project/source", projectRoot: "/project" }]);
  assert.equal(updates.length, 2); assert.equal(events.length, 1);
});

test("a rejected or unfinished rescan stream cannot report successful inventory preparation", async t => {
  let updates = 0;
  const mock = t.mock.method(globalThis, "fetch", async () => new Response('data: {"event":"error","message":"TEST changed original"}\n\n',
    { headers: { "content-type": "text/event-stream" } }));
  await assert.rejects(ingestInto("/project/source", "/project", () => updates++, { reuseTranscripts: true }), /changed original/);
  mock.mock.mockImplementation(async () => new Response('data: {"event":"progress","message":"TEST incomplete"}\n\n',
    { headers: { "content-type": "text/event-stream" } }));
  await assert.rejects(ingestInto("/project/source", "/project", () => updates++, { reuseTranscripts: true }), /manifest|complete|ended/i);
  assert.equal(updates, 0);
});
