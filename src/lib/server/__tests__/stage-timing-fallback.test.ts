import assert from "node:assert/strict";
import { test } from "node:test";
import {
  STAGE_TIMING_LINEAGE_ENV, stageTimingContext, stageTimingEnv, withInheritedStageTimingLineage,
  withStageTimingContext, withStageTimingFallback,
} from "../stage-timing-context";

// Exported SNIPER_TIMING_* from the caller's shell must not change these results.
for (const name of Object.values(STAGE_TIMING_LINEAGE_ENV)) delete process.env[name];

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

test("a long-lived process never applies exported lineage to unrelated jobs; only an explicit adoption does", async () => {
  process.env.SNIPER_TIMING_RUN_ID = "shell-exported-run";
  process.env.SNIPER_TIMING_TASK_ID = "shell-task";
  try {
    assert.ok(stageTimingContext().runId.startsWith("standalone:"), "the environment is not read implicitly");
    await withStageTimingFallback(fallback, async () => {
      await Promise.resolve(); assert.deepEqual(stageTimingContext(), fallback);
    });
    await withInheritedStageTimingLineage(async () => {
      await Promise.resolve();
      assert.deepEqual([stageTimingContext().runId, stageTimingContext().taskId], ["shell-exported-run", "shell-task"]);
      await withStageTimingFallback(fallback, async () => assert.equal(stageTimingContext().runId, "shell-exported-run"));
    });
    assert.ok(stageTimingContext().runId.startsWith("standalone:"), "adoption is scoped to its call tree");
  } finally { delete process.env.SNIPER_TIMING_RUN_ID; delete process.env.SNIPER_TIMING_TASK_ID; }
});
