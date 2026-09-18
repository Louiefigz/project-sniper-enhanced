import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot } from "../auto-edit-authority-snapshot";
import { capturePipelineAssets } from "../auto-edit-pipeline-assets";

test("code snapshots include native implementation but exclude materialized runtime and render caches", () => {
  const files = capturePipelineAssets(process.cwd());
  const names = files.map(row => row.path);
  assert.ok(names.includes("scripts/producer/studio/runtime/patches.json"));
  assert.ok(names.includes("scripts/producer/studio/native_short_export.py"));
  assert.ok(names.includes("src/app/api/producer/native-short/route.ts"));
  assert.ok(names.every(name => !name.includes("/.sniper-native-runtime/") && !name.includes("/artifacts/")));
});

function writeFixture(root: string, relative: string, content: string): void {
  const target = path.join(root, relative);
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, content);
}

function pythonSnapshot(repository: string, ctx: AutoEditCtx): unknown {
  const script = "import json,sys; from palmier.quality_hash import authority_snapshot; print(json.dumps(authority_snapshot(json.load(sys.stdin))))";
  const result = spawnSync(path.join(repository, ".venv/bin/python3"), ["-c", script], {
    encoding: "utf8", input: JSON.stringify(ctx),
    env: { ...process.env, PYTHONPATH: path.join(repository, "scripts/producer") },
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test("legacy TS and Python authority ignore generated caches but retain code changes", () => {
  const repository = process.cwd(), root = mkdtempSync(path.join(os.tmpdir(), "sniper-legacy-cache-"));
  const ctx: AutoEditCtx = { dir: path.join(root, "project/producer"), scope: "produced",
    planPath: path.join(root, "project/producer/edit_plan.json"), manifestPath: path.join(root, "project/source/manifest.json"),
    transcriptsDir: path.join(root, "project/source"), intent: { mode: "short", lanes: {} } };
  try {
    writeFixture(root, "scripts/producer/example.py", "print('original')\n");
    writeFixture(root, "project/producer/edit_plan.json", '{"planVersion":1,"cutTrack":[]}');
    writeFixture(root, "project/source/manifest.json", '{"sources":[]}');
    process.chdir(root);
    const original = autoEditAuthoritySnapshot(ctx);
    assert.deepEqual(pythonSnapshot(repository, ctx), original);
    writeFixture(root, "templates/motion/.sniper-native-runtime/test/frame.png", "TEST cache bytes");
    writeFixture(root, "scripts/producer/artifacts/test/result.json", '{"generated":true}');
    assert.deepEqual(autoEditAuthoritySnapshot(ctx), original);
    assert.deepEqual(pythonSnapshot(repository, ctx), original);
    writeFixture(root, "scripts/producer/example.py", "print('revised')\n");
    const changed = autoEditAuthoritySnapshot(ctx);
    assert.notEqual(changed.pipelineDigest, original.pipelineDigest);
    assert.deepEqual(pythonSnapshot(repository, ctx), changed);
  } finally {
    process.chdir(repository);
    rmSync(root, { recursive: true, force: true });
  }
});
