import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  planRefitEvent,
  resolvePlanRefitDecision,
} from "../../../app/api/_lib/plan-refit-transaction";

function unknownProvenanceFailsClosed(): void {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-refit-provenance-"));
  const planPath = path.join(dir, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1,
    cutTrack: [{ sourceId: "raw", start: 10, end: 20 }],
    graphicsTrack: [{ outStart: 1, outEnd: 2 }],
  }));
  try {
    const current = readFileSync(planPath, "utf8");
    assert.throws(
      () => resolvePlanRefitDecision(dir, planPath, { kind: "unknown" }),
      /provenance is unknown; refusing to infer a refit/,
    );
    assert.equal(readFileSync(planPath, "utf8"), current,
      "a failed provenance check never mutates the plan");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function refitEventDistinguishesApplicationFromReuse(): void {
  const receipt = {
    schemaVersion: 2 as const,
    transactionState: "committed" as const,
    source: "surgical-cut" as const,
    createdAt: new Date().toISOString(),
    inputPlanHash: "input", planHash: "plan",
    sourceCutHash: "source", targetCutHash: "target",
    sourceCutTrack: [], targetCutTrack: [], remapped: 2, dropped: 0, changes: [],
  };
  assert.deepEqual(
    [planRefitEvent(receipt).application, planRefitEvent(receipt).alreadyApplied],
    ["newly-applied", false],
  );
  assert.deepEqual(
    [planRefitEvent(receipt, "reused").application,
      planRefitEvent(receipt, "reused").alreadyApplied],
    ["reused", true],
  );
}

unknownProvenanceFailsClosed();
refitEventDistinguishesApplicationFromReuse();
console.log("plan-refit-provenance.test.ts: all assertions passed");
