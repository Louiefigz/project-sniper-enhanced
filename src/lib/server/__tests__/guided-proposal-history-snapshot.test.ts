import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { linkSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { observeHistoricalProposalSnapshot } from "../guided-proposal-history-snapshot";
import type { AutoEditPipelineAuthority } from "@/app/api/producer/auto-edit/stream";

/** Synthetic immutable metadata only; no executed compiler, review, media or approval claim. */
function snapshotFixture(version: 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-history-snapshot-")));
  const schemaName = `schemas/producer/treatment-proposal-v${version}.schema.json`;
  const source = Buffer.from("// TEST ONLY historical captured TypeScript, never executed.\n");
  const contents = new Map([["src/test-executor.ts", source], [schemaName, readFileSync(schemaName)]]);
  const files = [...contents].map(([name, bytes]) => {
    const file = path.join(root, name); mkdirSync(path.dirname(file), { recursive: true }); writeFileSync(file, bytes);
    return { path: name, hash: createHash("sha256").update(bytes).digest("hex") };
  });
  const pipeline: AutoEditPipelineAuthority = { schemaVersion: 1, runId: randomUUID(), digest: canonicalJsonSha256(files),
    snapshotRoot: root, lockPath: path.join(root, "pipeline-lock.json"), files };
  writeFileSync(pipeline.lockPath, canonicalJson({ schemaVersion: 1, state: "pinned", runId: pipeline.runId, digest: pipeline.digest, files }));
  const compiler = { files: files.map((row) => ({ name: row.path, sha256: row.hash })),
    totalBytes: [...contents.values()].reduce((sum, bytes) => sum + bytes.length, 0),
    scope: "captured-ts-source-and-runtime-config-not-built-bundle",
    runtime: { node: "TEST-OLD-NODE", v8: "TEST-OLD-V8", platform: "test-platform", arch: "test-arch" },
    schemaHash: files[1].hash, schema: JSON.parse(contents.get(schemaName)!.toString()) as Record<string, unknown> };
  return { root, pipeline, compiler, source, sourceFile: path.join(root, "src/test-executor.ts"),
    cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

for (const version of [2, 3, 4, 5, 6, 7, 8, 9, 10] as const) {
  test(`historical V${version} snapshot retains exact pinned bytes without asserting current runtime equivalence`, () => {
    const fixture = snapshotFixture(version);
    try {
      const observed = observeHistoricalProposalSnapshot(fixture.pipeline, fixture.compiler);
      assert.equal(observed.observedBytes, fixture.compiler.totalBytes); assert.equal(observed.fileCount, 2);
      assert.equal(observed.pipelineDigest, fixture.pipeline.digest);
      const wrongSchema = structuredClone(fixture.compiler);
      (wrongSchema.schema.properties as Record<string, Record<string, unknown>>).schemaVersion.const = version === 2 ? 3 : 2;
      assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, wrongSchema));
    } finally { fixture.cleanup(); }
  });
}

test("historical snapshot rejects corrupted bytes, omitted TS, swapped metadata and linked artifacts", () => {
  const fixture = snapshotFixture(3);
  try {
    writeFileSync(fixture.sourceFile, "// TEST corruption");
    assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, fixture.compiler), /bytes changed/);
    writeFileSync(fixture.sourceFile, fixture.source);
    assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, { ...fixture.compiler, files: fixture.compiler.files.slice(1),
      totalBytes: fixture.compiler.totalBytes - fixture.source.length }), /omitted/);
    assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, { ...fixture.compiler, totalBytes: fixture.compiler.totalBytes + 1 }), /byte/);
    for (const runtime of [{ ...fixture.compiler.runtime, extra: true }, { ...fixture.compiler.runtime, node: "" }, null]) {
      assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, { ...fixture.compiler, runtime }));
    }
    const duplicate = path.join(fixture.root, "hard-linked.ts"); linkSync(fixture.sourceFile, duplicate);
    assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, fixture.compiler), /bounded regular/); unlinkSync(duplicate);
    const target = path.join(fixture.root, "held-source.ts"); writeFileSync(target, fixture.source); unlinkSync(fixture.sourceFile);
    symlinkSync(target, fixture.sourceFile); assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, fixture.compiler));
  } finally { fixture.cleanup(); }
});

test("historical V9 support does not admit unknown/string schema versions or a substituted schema hash", () => {
  const fixture = snapshotFixture(9);
  try {
    for (const version of [0, 1, 11, 99, "7", "8", "9", "10", null]) {
      const compiler = structuredClone(fixture.compiler);
      (compiler.schema.properties as Record<string, Record<string, unknown>>).schemaVersion.const = version;
      assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline, compiler), /Unsupported historical proposal schema/);
    }
    assert.throws(() => observeHistoricalProposalSnapshot(fixture.pipeline,
      { ...fixture.compiler, schemaHash: "a".repeat(64) }), /schema snapshot changed/);
  } finally { fixture.cleanup(); }
});
