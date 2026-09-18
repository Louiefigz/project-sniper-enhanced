import assert from "node:assert/strict";
import { test } from "node:test";
import { stageTimingContext, stageTimingEnv, withStageTimingContext, withStageTimingFallback } from "../stage-timing-context";

const fallback = { runId: "fallback-job", attemptId: "job-fence", attemptNo: 1 };

test("a standalone source helper obtains job identity without changing ambient context or environment", async () => {
  const original = stageTimingContext(), environment = { ...process.env };
  await withStageTimingFallback(fallback, async () => {
    await Promise.resolve(); assert.deepEqual(stageTimingContext(), fallback);
    assert.equal(stageTimingEnv().SNIPER_TIMING_ATTEMPT_ID, "job-fence");
  });
  assert.deepEqual(stageTimingContext(), original); assert.deepEqual({ ...process.env }, environment);
});

test("concurrent proposal/readiness executions keep their own UUID and parent instead of the shared job fence", async () => {
  const original = stageTimingContext();
  await Promise.all(["proposal:actual-execution-1", "proposal-readiness:actual-execution-2"].map(async (attemptId, index) => {
    const actual = { runId: "original-run", attemptId, attemptNo: 3, parentSpanId: `parent-${index}` };
    await withStageTimingContext(actual, () => withStageTimingFallback(fallback, async () => {
      await Promise.resolve(); assert.deepEqual(stageTimingContext(), actual);
      assert.equal(stageTimingEnv().SNIPER_TIMING_PARENT_SPAN_ID, actual.parentSpanId);
      assert.equal(stageTimingEnv().SNIPER_TIMING_ATTEMPT_ID, attemptId);
    }));
  }));
  assert.deepEqual(stageTimingContext(), original);
});
