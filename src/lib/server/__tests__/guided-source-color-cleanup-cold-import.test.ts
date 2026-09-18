/** Fresh production imports only: no fixture preloads, providers, media, cleanup or native invocation. */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";

const ROOT = path.resolve(__dirname, "../../../..");
const ENTRIES = [
  "guided-source-color-cleanup-final-commit", "guided-source-color-cleanup-final-read",
  "guided-source-color-cleanup-adoption", "guided-source-color-cleanup-attempt-media",
  "guided-source-color-cleanup-attempt-read", "guided-source-color-cleanup-attempt",
  "guided-source-color-cleanup-history", "guided-source-color-cleanup-pending-read",
  "guided-source-color-cleanup-pending-commit", "guided-source-color-cleanup-recovery",
  "guided-opening-cleanup-store", "guided-opening-cleanup", "guided-opening-process",
  "guided-source-color-resource-recovery",
] as const;

// Each first import starts in a new module cache. Subsequent assertions do not reorder that entry.
const CHILD = String.raw`
require("tsx/cjs");
const assert = require("node:assert/strict");
const path = require("node:path");
function read(name) { return require(path.resolve("src/lib/server/" + name + ".ts")); }
const first = read(process.argv[1]);
assert(Object.keys(first).length > 0);
const recovery = read("guided-source-color-cleanup-recovery").sourceColorCleanupRecoveryDependencies;
const final = read("guided-source-color-cleanup-final-commit").sourceColorFinalCommitDependencies;
const readback = read("guided-source-color-cleanup-final-read").sourceColorFinalCleanupReadDependencies;
const pending = read("guided-source-color-cleanup-pending-read").sourceColorCleanupPendingReadDependencies;
const attempt = read("guided-source-color-cleanup-attempt-read").sourceColorCleanupAttemptReadDependencies;
const adoption = read("guided-source-color-cleanup-adoption").sourceColorCleanupAdoptionDependencies;
const store = read("guided-opening-cleanup-store").openingCleanupStoreDependencies;
assert.equal(recovery.final, final);
assert.equal(recovery.read, readback);
assert.equal(recovery.pending, pending);
assert.equal(adoption.history, attempt);
assert.equal(store.completedHistory, attempt);
assert.equal(recovery.completed, recovery.completed);
assert.equal(recovery.completed.history, attempt);
assert.equal(recovery.completed.claim, adoption.claim);
assert.equal(recovery.completed.workspace, adoption.workspace);
assert.equal(recovery.completed.resource, read("guided-source-color-resource-recovery").sourceColorResourceRecoveryDependencies);
assert.equal(recovery.resource, read("guided-source-color-resource-recovery").sourceColorRetirementResourceRecoveryDependencies);
assert.equal(final.history, read("guided-source-color-cleanup-pending-read").readRetainedSourceColorCleanupPending);
assert.equal(recovery.acquireProject, read("guided-cut-v2-store").acquireGuidedMutation);
assert.throws(() => read("guided-source-color-cleanup-final-commit").assertCommittedSourceColorCleanupMetadata({}), /actual original commit/);
process.stdout.write("actual cold imports and original dependencies verified\n");
`;

for (const entry of ENTRIES) test(`cold ${entry} preserves actual default dependency identities`, () => {
  const result = spawnSync(process.execPath, ["-e", CHILD, entry], {
    cwd: ROOT, encoding: "utf8", timeout: 15_000, killSignal: "SIGKILL", maxBuffer: 1024 * 1024,
    env: { HOME: process.env.HOME, PATH: process.env.PATH, TMPDIR: process.env.TMPDIR, NODE_ENV: "test" },
  });
  assert.ifError(result.error);
  assert.equal(result.signal, null, result.stderr);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "actual cold imports and original dependencies verified\n");
});
