import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { acquireProjectMutationLease } from "../project-mutation-lease";

// scripts/infra/project-intent.ts: the command-line write of project.json's stored intent that
// buyers' own Codex or Claude Code use instead of the retired app route. It must refuse what the
// app refused (no ingested media, an invalid intent, a busy project) and save what it saved.
const REPO = path.resolve(__dirname, "../../../..");
const CLI = path.join(REPO, "scripts/infra/project-intent.ts");
const root = mkdtempSync(path.join(os.tmpdir(), "sniper-intent-cli-"));

function run(...args: string[]) {
  const done = spawnSync(process.execPath, ["--import", "tsx", CLI, ...args],
    { cwd: REPO, encoding: "utf8", timeout: 60_000 });
  return { code: done.status, out: done.stdout, err: done.stderr };
}

const intent = { mode: "longform", scope: "produced", lanes: {}, preset: "longform-produced" };

try {
  const notIngested = run(root, "--intent", JSON.stringify(intent));
  assert.equal(notIngested.code, 1, notIngested.err);
  assert.match(notIngested.err, /not an ingested project/);
  assert.equal(existsSync(path.join(root, "project.json")), false, "nothing is written for a folder without media");

  mkdirSync(path.join(root, "source"), { recursive: true });
  writeFileSync(path.join(root, "source", "asset_manifest.json"), JSON.stringify({ broll: [] }));
  const saved = run(root, "--intent", JSON.stringify(intent));
  assert.equal(saved.code, 0, saved.err);
  const stored = JSON.parse(readFileSync(path.join(root, "project.json"), "utf8"));
  assert.equal(stored.origin, "raw");
  assert.deepEqual(stored.requestedIntent, intent);
  assert.deepEqual(stored.resolvedIntent.lanes, { broll: "off" }, "the app's own capability reconciliation ran");
  assert.equal(stored.history.at(-1).stage, "intent");

  const shown = run(path.join(root, "producer"));
  assert.equal(shown.code, 0, shown.err);
  assert.equal(JSON.parse(shown.out).intent.scope, "produced", "the producer/ folder resolves to its project");

  const before = readFileSync(path.join(root, "project.json"), "utf8");
  const invalid = run(root, "--intent", JSON.stringify({ ...intent, scope: "trm" }));
  assert.equal(invalid.code, 1);
  assert.match(invalid.err, /edit request not saved/);
  assert.equal(readFileSync(path.join(root, "project.json"), "utf8"), before, "a refused intent changes nothing");

  const held = acquireProjectMutationLease(root, "a render");
  assert.ok(held.lease, "test setup: lease");
  try {
    const busy = run(root, "--intent", JSON.stringify(intent));
    assert.equal(busy.code, 1);
    assert.match(busy.err, /busy with a render/);
  } finally {
    held.lease.release();
  }
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("project-intent-cli.test.ts: all assertions passed");
