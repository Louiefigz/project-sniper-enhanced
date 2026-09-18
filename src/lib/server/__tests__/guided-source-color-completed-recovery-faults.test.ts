/** Actual completed recovery/CAS/leases, with native and claim admission explicitly TEST-only. No dependency files are fault targets. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { completedRecoveryFixture } from "./_guided-source-color-completed-recovery-fixture";
import { adoptionFaultFile, replaceAdoptionFile } from "./_guided-source-color-cleanup-adoption-fixture";

type Fixture = Awaited<ReturnType<typeof completedRecoveryFixture>>;

/** Same parsed TEST preparation, different original raw SHA; target is the existing canonical, regular, single-link allowlist. */
function stalePreparedBytes(f: Fixture): void {
  const file = adoptionFaultFile(f, "prepared"), temporary = path.join(path.dirname(file), `TEST-stale-prepared-${randomUUID()}.json`);
  fs.writeFileSync(temporary, Buffer.concat([fs.readFileSync(file), Buffer.from("\n")]), { flag: "wx", mode: 0o600 });
  fs.renameSync(temporary, file);
}

/** Failures after final CAS preserve real proof and never imply another native cleanup or approval. */
function assertFinalRetained(f: Fixture): void {
  assert.equal(f.calls.length, 1); assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 1);
  assert(!fs.existsSync(f.files.project)); assert(!fs.existsSync(f.files.resource)); assert(!fs.existsSync(f.files.active));
  assert(fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
  const pointer = observeHumanCutJob(f.recoveryInput.dir).job.guidedHandoffV2!;
  assert(pointer.openingCleanupHash); assert.equal(pointer.openingExecutionClaimHash, undefined);
  assert.equal(pointer.openingProcessOutcomeHash, undefined); assert.equal(pointer.openingMediaSelectionHash, undefined);
}

test("failed global acquisition with actual no-op release retains both locks and reports AggregateError", async t => {
  const f = await completedRecoveryFixture(t); let release: (() => void) | undefined;
  f.recoveryCallbacks.resourceAfter = () => {
    release = f.resources[0].release; f.resources[0].release = () => {}; f.allowance.ms = 0;
  };
  try {
    await assert.rejects(f.run(), error => {
      assert(error instanceof AggregateError); assert.match(String(error.errors[0]), /allowance|deadline|remainder/);
      assert.match(String(error.errors[1]), /release is unverified/); return true;
    });
    assert(fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.resource)); assert(fs.existsSync(f.files.active));
    assert(!fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure)); assert.equal(f.calls.length, 1);
    assert.equal(observeHumanCutJob(f.recoveryInput.dir).sha256, f.before.sha256);
  } finally { if (release) f.resources[0].release = release; }
});

for (const fault of ["raw-prepared", "journal", "selector"] as const) {
  test(`awaited actual project acquisition cannot adopt stale ${fault}`, async t => {
    const f = await completedRecoveryFixture(t); let fired = false;
    f.recoveryCallbacks.projectBefore = async () => {
      await Promise.resolve(); fired = true;
      if (fault === "raw-prepared") stalePreparedBytes(f);
      if (fault === "journal") replaceAdoptionFile(f, "journal");
      if (fault === "selector") f.recoveryInput.preparedSha256 = "0".repeat(64);
    };
    await assert.rejects(f.run(), /stale|original|identity|changed|hash|SHA/i); assert(fired);
    assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 0); assert.equal(f.calls.length, 1);
    assert(!fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
    assert.equal(observeHumanCutJob(f.recoveryInput.dir).sha256, f.before.sha256);
  });
}

for (const fault of ["claim", "job"] as const) {
  test(`actual current claim reader cannot substitute ${fault} under the original requested journal`, async t => {
    const f = await completedRecoveryFixture(t), actual = f.recoveryControls.completed.claim; let reads = 0;
    // Preserve all five actual TEST metadata refs; require the production guard, not a fixture-only deep-equality assertion, to reject.
    f.recoveryControls.completed.history.media = (_held, capture) => { f.media.files.forEach(capture); };
    f.recoveryControls.completed.claim = dir => {
      const value = actual(dir); reads++;
      if (fault === "claim") value.claimHash = "0".repeat(64); else value.job.token += "-TEST-substitution";
      return value;
    };
    await assert.rejects(f.run(), /original current claim changed/); assert.equal(reads, 1);
    assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 0); assert.equal(f.calls.length, 1);
    assert(!fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
  });
}

for (const fault of ["request", "output"] as const) {
  test(`last original clock callback after releases cannot conceal changed ${fault}`, async t => {
    const f = await completedRecoveryFixture(t); let fired = false;
    f.adoptionCallbacks.remaining = () => {
      if (fired || !fs.existsSync(f.files.ack) || fs.existsSync(f.files.project)) return;
      fired = true;
      if (fault === "request") f.recoveryInput.cleanupAttemptId = randomUUID(); else replaceAdoptionFile(f, "output");
    };
    await assert.rejects(f.run(), /original|changed/); assert(fired); assertFinalRetained(f);
  });
}

for (const fault of ["request", "output", "expiry"] as const) {
  test(`actual final timing append cannot conceal ${fault} after completed recovery releases`, async t => {
    const f = await completedRecoveryFixture(t), actualWrite = fs.writeSync; let fired = false;
    t.mock.method(fs, "writeSync", (...args: Parameters<typeof fs.writeSync>) => {
      const result = actualWrite(...args), text = typeof args[1] === "string" ? args[1] : "";
      if (fired || !text.includes('"stage":"guided_opening_source_color_completion_recovery"') || !text.includes('"event":"end"')) return result;
      fired = true; assert(!fs.existsSync(f.files.project)); assert(!fs.existsSync(f.files.resource));
      if (fault === "request") f.recoveryInput.preparedSha256 = "0".repeat(64);
      if (fault === "output") replaceAdoptionFile(f, "output");
      if (fault === "expiry") f.allowance.ms = 0;
      return result;
    });
    await assert.rejects(f.run(), /allowance|original|changed/); assert(fired); assertFinalRetained(f);
  });
}
