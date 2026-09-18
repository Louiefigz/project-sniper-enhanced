import assert from "node:assert/strict";
import { mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { bodyCleanupFixture } from "./_guided-body-cleanup-fixture";
import { readBodyCleanupControl } from "../guided-body-cleanup-control";
import { readBodyPhase } from "../guided-body-phase";
import { readOwnedBodyProcess } from "../guided-body-process";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { observeHistoricalPipelineSnapshot } from "../guided-proposal-history-snapshot";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";

test("known recovery controls survive media/provenance deletion, without granting full cleanup or selection", async () => {
  const f = await bodyCleanupFixture();
  try {
    const before = readFileSync(f.base.jobPath), first = readBodyCleanupControl(f.dir);
    assert.equal(first.held.activationHash, f.activationHash);
    for (const name of ["openingInput", "openingResult", "admissionClaim", "heldInput", "budgetAdmission", "budgetPrecommit"] as const) {
      unlinkSync(f.input.references[name].path);
      assert.equal(readBodyCleanupControl(f.dir).factHash, f.factHash);
    }
    assert.throws(() => readBodyPhase(f.dir, "process"));
    assert.throws(() => readOwnedBodyProcess(first), /body intent|unknown|missing/i); // TEST data is never actual stop proof.
    assert.deepEqual(readFileSync(f.base.jobPath), before);
    assert.equal(observeHumanCutJob(f.dir).job.guidedHandoffV2?.bodyCleanupHash, undefined);
  } finally { await f.dispose(); }
});

test("cleanup requires exact private activation/input/outcome and known journal ancestry, not resealed or transplanted metadata", async () => {
  const f = await bodyCleanupFixture();
  try {
    const files = [f.activationRecord.path, f.inputRecord.path, f.outcome.path,
      path.join(f.dir, "human-cut-job-snapshots", `${f.activatedJournalHash}.json`), f.input.references.approvedSnapshot.path];
    for (const file of files) {
      const bytes = readFileSync(file); writeFileSync(file, "{}");
      assert.throws(() => readBodyCleanupControl(f.dir)); writeFileSync(file, bytes);
    }
    const job = readFileSync(f.base.jobPath), value = JSON.parse(job.toString()); value.message += " unrelated descendant";
    writeFileSync(f.base.jobPath, JSON.stringify(value)); assert.throws(() => readBodyCleanupControl(f.dir), /edge/);
    writeFileSync(f.base.jobPath, job); assert.equal(readBodyCleanupControl(f.dir).factHash, f.factHash);
  } finally { await f.dispose(); }
});

test("cleanup refuses changed exact runtime and pinned code/lock; old code is never silently replaced", async () => {
  const f = await bodyCleanupFixture();
  try {
    for (const file of [f.runtime.dockerPath, f.runtime.imageApprovalPath]) {
      const bytes = readFileSync(file); writeFileSync(file, "{}");
      assert.throws(() => readBodyCleanupControl(f.dir)); writeFileSync(file, bytes);
    }
    const snapshotRoot = path.join(f.root, "TEST-files"); mkdirSync(snapshotRoot);
    const script = path.join(snapshotRoot, "TEST-never-executed.py"); writeFileSync(script, "# TEST code pin\n");
    const files = [{ path: path.basename(script), hash: observeCutPreviewFile(script, 1024).sha256 }], digest = hash(files);
    const lockPath = path.join(f.root, "TEST-lock.json"), lock = { schemaVersion: 1 as const, state: "pinned", runId: "TEST", digest, files };
    writeFileSync(lockPath, JSON.stringify(lock)); const pipeline = { schemaVersion: 1 as const, runId: "TEST", digest, files, snapshotRoot, lockPath };
    assert.equal(observeHistoricalPipelineSnapshot(pipeline).hashes.size, 1);
    writeFileSync(script, "# changed\n"); assert.throws(() => observeHistoricalPipelineSnapshot(pipeline), /bytes changed/);
    writeFileSync(script, "# TEST code pin\n"); writeFileSync(lockPath, JSON.stringify({ ...lock, digest: "b".repeat(64) }));
    assert.throws(() => observeHistoricalPipelineSnapshot(pipeline), /immutable lock/);
  } finally { await f.dispose(); }
});
