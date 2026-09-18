/** Destination and input guards fail before any actual media/CLI operation. */
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, renameSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { POST } from "@/app/api/producer/ingest/route";
import { assertIngestInputAuthority, assertSameIngestAuthority, existingIngestAuthority } from "@/app/api/producer/ingest/authority";
import { parseRequest } from "@/app/api/producer/ingest/request";
import { nativeShortAppFixture } from "./_native-short-app-fixture";

function request(body: Record<string, unknown>) {
  return new NextRequest("http://localhost/api/producer/ingest", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}

test("competing or malformed targets and transcription flags cannot fall through to another mode", async () => {
  const f = nativeShortAppFixture();
  try {
    for (const fields of [{ projectRoot: f.root, outDir: f.dir }, { projectRoot: "", outDir: f.dir },
      { projectRoot: false }, { outDir: null }, { outDir: 8 }, { noTranscribe: "true" }, { reuseTranscripts: "true" }]) {
      const response = await POST(request({ inputPath: f.source, ...fields }));
      assert.equal(response.status, 400, JSON.stringify(fields));
    }
    const parsed = await parseRequest(request({ inputPath: f.source, outDir: f.dir, noTranscribe: true }));
    assert.ok(!(parsed instanceof Response)); assert.equal(parsed.noTranscribe, true);
  } finally { f.cleanup(); }
});

test("managed source, producer and root destinations check the same actual guided checkpoint", async () => {
  const f = nativeShortAppFixture(), manifest = readFileSync(f.manifestPath), journal = readFileSync(f.jobPath);
  try {
    for (const outDir of [f.root, path.dirname(f.manifestPath), f.dir]) {
      assert.deepEqual(existingIngestAuthority({ outDir }), { root: f.root, producerDir: f.dir });
      const response = await POST(request({ inputPath: f.source, outDir, reuseTranscripts: true }));
      assert.equal(response.status, 409, outDir);
    }
    assert.deepEqual(readFileSync(f.manifestPath), manifest); assert.deepEqual(readFileSync(f.jobPath), journal);
  } finally { f.cleanup(); }
});

test("nested existing or absent destinations cannot acquire a separate lease beneath a checkpoint", async () => {
  const f = nativeShortAppFixture();
  try {
    for (const outDir of [path.join(f.dir, "private"), path.join(path.dirname(f.manifestPath), "broll")]) {
      assert.throws(() => existingIngestAuthority({ outDir }), /Nested project/);
      mkdirSync(outDir);
      assert.equal((await POST(request({ inputPath: f.source, outDir, noTranscribe: true }))).status, 422);
    }
  } finally { f.cleanup(); }
});

test("symlinked managed source and aliased output cannot redirect writes outside the lease", async () => {
  const f = nativeShortAppFixture(), external = path.join(f.workspace, "external"); mkdirSync(external);
  try {
    const source = path.dirname(f.manifestPath), renamed = path.join(f.root, "source-original");
    renameSync(source, renamed); symlinkSync(external, source);
    assert.equal((await POST(request({ inputPath: path.join(renamed, "source.mp4"), projectRoot: f.root, noTranscribe: true }))).status, 422);
    assert.throws(() => existingIngestAuthority({ outDir: source }), /canonical|symbolic/);
    unlinkSync(source); symlinkSync(path.join(f.workspace, "absent"), source);
    assert.throws(() => existingIngestAuthority({ projectRoot: f.root }), /dangling/);
  } finally { f.cleanup(); }
});

test("untagged layouts retain checkpoint ownership and present malformed markers never become legacy absence", async () => {
  const f = nativeShortAppFixture();
  try {
    rmSync(path.join(f.root, "project.json"));
    assert.deepEqual(existingIngestAuthority({ outDir: path.dirname(f.manifestPath) }), { root: f.root, producerDir: f.dir });
    assert.equal((await POST(request({ inputPath: f.source, outDir: path.dirname(f.manifestPath), noTranscribe: true }))).status, 409);
    symlinkSync(path.join(f.workspace, "missing-marker"), path.join(f.root, "project.json"));
    assert.equal((await POST(request({ inputPath: f.source, outDir: path.dirname(f.manifestPath), noTranscribe: true }))).status, 422);
  } finally { f.cleanup(); }
});

test("foreign managed folder catalogs are protected while individual media file imports remain available", () => {
  const f = nativeShortAppFixture(), other = path.join(f.workspace, "other"); mkdirSync(other);
  try {
    mkdirSync(path.join(other, "source")); mkdirSync(path.join(other, "producer"));
    writeFileSync(path.join(other, "project.json"), '{"origin":"raw","history":[]}');
    const directory = { inputPath: path.dirname(f.manifestPath), projectRoot: other };
    assert.throws(() => assertIngestInputAuthority(directory), /another project/);
    assert.throws(() => assertIngestInputAuthority({ inputPath: path.dirname(f.manifestPath) }), /another project/);
    assert.doesNotThrow(() => assertIngestInputAuthority({ ...directory, inputPath: f.source }));
    assert.doesNotThrow(() => assertIngestInputAuthority({ inputPath: path.dirname(f.manifestPath), projectRoot: f.root }));
    const legacy = path.join(f.workspace, "legacy"); mkdirSync(legacy);
    assert.deepEqual(existingIngestAuthority({ outDir: legacy }), { root: legacy, producerDir: legacy });
  } finally { f.cleanup(); }
});


test("a standalone destination becoming managed cannot change the owner of its existing lease", () => {
  const f = nativeShortAppFixture(), parent = path.join(f.workspace, "new-owner"), outDir = path.join(parent, "source");
  mkdirSync(outDir, { recursive: true });
  try {
    const held = existingIngestAuthority({ outDir }); assert.ok(held);
    assert.deepEqual(held, { root: outDir, producerDir: outDir });
    assert.doesNotThrow(() => assertSameIngestAuthority(existingIngestAuthority({ outDir }), held));
    writeFileSync(path.join(parent, "project.json"), '{"origin":"raw"}');
    assert.throws(() => assertSameIngestAuthority(existingIngestAuthority({ outDir }), held), /ownership changed/);
    writeFileSync(path.join(parent, "project.json"), '{"notAProject":true}');
    assert.throws(() => existingIngestAuthority({ outDir }), /malformed/);
  } finally { f.cleanup(); }
});
