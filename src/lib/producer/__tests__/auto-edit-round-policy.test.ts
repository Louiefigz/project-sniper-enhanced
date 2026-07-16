import assert from "node:assert/strict";
import {
  MAX_PLANNING_REVIEW_ROUNDS,
  MAX_QC_RENDER_ROUNDS,
  planningBudgetViable,
  planningCanConverge,
  planningCapReached,
  qcCapReached,
  requiredPlanningRounds,
  VISUAL_REVIEW_LENSES,
} from "../../../app/api/producer/auto-edit/round-policy";

assert.equal(requiredPlanningRounds("trim"), 1);
assert.equal(requiredPlanningRounds("light"), 1);
assert.equal(requiredPlanningRounds("produced"), 2);
assert.equal(requiredPlanningRounds("full"), 2);
assert.equal(planningCanConverge("produced", 1, 0), false);
assert.equal(planningCanConverge("produced", 2, 0), true);
assert.equal(planningCanConverge("produced", 4, 1), false);
assert.equal(planningCapReached(MAX_PLANNING_REVIEW_ROUNDS), true);
assert.equal(qcCapReached(MAX_QC_RENDER_ROUNDS), true);
// One remaining full-width cycle can still produce both required cleans; a
// zero or too-narrow remainder cannot fund another revision.
assert.equal(planningBudgetViable(1, 2, 2), true);
assert.equal(planningBudgetViable(0, 2, 2), false);
assert.equal(planningBudgetViable(1, 1, 2), false);
assert.equal(planningBudgetViable(2, 1, 2), true);
assert.deepEqual(VISUAL_REVIEW_LENSES, ["composition", "editorial"]);

console.log("auto-edit-round-policy.test.ts: all assertions passed");
