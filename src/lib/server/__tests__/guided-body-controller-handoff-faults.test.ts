/** Actual writer/activation CAS and original clock; only TEST time advances, never source/tool mutation. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { activateFreshGuidedBody } from "../guided-body-activation";
import type { FreshBodyAdmission } from "../guided-body-claim";
import { BODY_DEADLINE_POLICY } from "../guided-body-deadline";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { bodyControllerSourcesFixture, type BodyControllerSourcesFixture } from "./_guided-body-controller-sources-fixture";

interface TailClock { now: number; committed: boolean; sampled: boolean; advanced: boolean }

/** Narrow the real wall budget at actual CAS; charge only a later exact TEMP source metadata read. */
function activationTail(t: TestContext, f: BodyControllerSourcesFixture, context: FreshBodyAdmission, clock: TailClock) {
  const journal = autoEditJobPath(context.dir), rename = fs.renameSync, stat = fs.lstatSync;
  const watermark = path.join(context.dir, "generation-clock-observations",
    context.budget.admission.clockHash, `${context.operation.executionId}.json`);
  assert.equal(f.copied, path.join(f.root, "TEST-original-pipeline", "scripts/producer/guided-body.ts"));
  const publication = t.mock.method(fs, "renameSync", (from: fs.PathLike, to: fs.PathLike) => {
    rename(from, to);
    if (!clock.committed && String(to) === journal) {
      clock.committed = true; t.mock.timers.tick(BODY_DEADLINE_POLICY.wholeAttemptMs - 100);
    }
    if (clock.committed && String(to) === watermark) clock.sampled = true;
  });
  const metadata = t.mock.method(fs, "lstatSync", ((file: fs.PathLike, options?: { bigint?: boolean }) => {
    const value = stat(file, options as { bigint: true });
    if (clock.sampled && !clock.advanced && String(file) === f.copied) {
      clock.advanced = true; clock.now += 101;
    }
    return value;
  }) as typeof fs.lstatSync);
  return () => { metadata.mock.restore(); publication.mock.restore(); };
}

test("actual activation tail cannot spend a smaller original post-CAS remainder against the old source cutoff", async t => {
  const f = await bodyControllerSourcesFixture(t);
  const clock: TailClock = { now: performance.now(), committed: false, sampled: false, advanced: false };
  const monotonic = t.mock.method(performance, "now", () => clock.now);
  try {
    await f.run(async ({ context }) => {
      const restore = activationTail(t, f, context, clock);
      let failure: unknown;
      try { activateFreshGuidedBody(context); } catch (error) { failure = error; }
      finally { restore(); }
      assert(clock.committed, "the actual activation journal CAS completed");
      assert(clock.sampled, "the actual original budget published its narrower post-CAS watermark");
      assert(clock.advanced, "the final original source metadata IO consumed the remaining 100 ms");
      assert.throws(() => context.budget.remainingMs(), /deadline-exceeded|expired/);
      assert(observeHumanCutJob(context.dir).job.guidedHandoffV2?.bodyActivationHash,
        "completed CAS evidence remains retained after a failed return; no rollback or retry");
      assert(failure instanceof Error, "activation returned success after its original remaining budget expired");
      assert.match(failure.message, /expired|deadline|budget/);
    });
  } finally { monotonic.mock.restore(); }
});
