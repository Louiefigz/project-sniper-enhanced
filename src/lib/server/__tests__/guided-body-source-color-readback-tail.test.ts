/** Actual admission→process→cleanup→candidate CAS with native/readiness/tool TEST leaves; never body/media approval. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { assertHeldBodyResultMetadata } from "../guided-body-result";
import { readQualifiedBodyCandidate } from "../guided-body-readback";
import { bodySourceReadbackFixture } from "./_guided-body-source-color-readback-fixture";

test("actual source2 readback candidate protocol keeps all three CASes and real result/history readers", async t => {
  const fixture = await bodySourceReadbackFixture(t);
  await fixture.run(async f => {
    assert.equal(f.protocol.process.fact.phase, "process"); assert.equal(f.protocol.cleanup.fact.phase, "cleanup");
    const result = await f.qualify();
    assert.equal(result.fact.phase, "candidate"); assert.equal(f.calls.length, 1);
    assert.equal(result.current.job.guidedHandoffV2?.bodyCandidateHash, result.factHash);
    const selected = readQualifiedBodyCandidate(f.context.dir);
    assert.equal(selected.candidate.path, f.protocol.candidate);
    assert.equal(selected.selected.completion.schemaVersion, 2); assertHeldBodyResultMetadata(selected.selected);
    assert.equal(selected.selected.sourceBytesObserved, false); assert.equal(selected.selected.mediaBytesObserved, false);
    assert(f.context.budget.remainingMs() > 0);
  });
});

test("source2 readback cannot return success after candidate CAS exhausts its original allowance", async t => {
  const fixture = await bodySourceReadbackFixture(t);
  await fixture.run(async f => {
    const target = autoEditJobPath(f.context.dir), rename = fs.renameSync;
    assert(target.startsWith(fixture.root + "/")); assert.equal(fs.realpathSync(target), target);
    let committed = false;
    const fault = t.mock.method(fs, "renameSync", ((...args: Parameters<typeof fs.renameSync>) => {
      const result = rename(...args);
      if (!committed && args[1] === target) {
        const row = observeHumanCutJob(f.context.dir);
        if (row.job.guidedHandoffV2?.bodyCandidateHash) { committed = true; t.mock.timers.tick(60 * 60_000); }
      }
      return result;
    }) as typeof fs.renameSync);
    let error: unknown;
    try { await f.qualify(); } catch (failure) { error = failure; }
    finally { fault.mock.restore(); }
    assert(committed, "TEST reached the actual final candidate journal CAS");
    assert.equal(f.calls.length, 1); assert(observeHumanCutJob(f.context.dir).job.guidedHandoffV2?.bodyCandidateHash);
    assert(error instanceof Error, "candidate returned success after original body allowance expired");
    assert.match(String(error), /deadline|expired|exhausted/u);
  });
});
