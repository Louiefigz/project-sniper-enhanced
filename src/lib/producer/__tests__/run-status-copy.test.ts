import assert from "node:assert/strict";
import {
  elapsedLabel,
  eventTimestamp,
  heartbeatLabel,
  plainRunFailureMessage,
  runTimingLabel,
} from "../run-status-copy";

const now = Date.parse("2026-07-12T10:02:03.000Z");
assert.equal(elapsedLabel("2026-07-12T10:00:00.000Z", now), "2m 3s elapsed");
assert.equal(heartbeatLabel("2026-07-12T10:02:00.000Z", now), "last progress 3s ago");
assert.equal(runTimingLabel({
  kind: "auto_edit",
  status: "running",
  phase: "planning_review",
  startedAt: "2026-07-12T10:00:00.000Z",
  updatedAt: "2026-07-12T10:02:00.000Z",
  message: "Reviewing",
  events: [],
}, now), "2m 3s elapsed · last progress 3s ago");
assert.equal(eventTimestamp("2026-07-12T10:02:00.000Z"), "2026-07-12 10:02:00Z");

assert.match(plainRunFailureMessage("No eligible b-roll assets were found"), /cutaways were available/i);
assert.match(plainRunFailureMessage("Deterministic planning gates failed with 2 issues"), /did not pass/i);
assert.match(plainRunFailureMessage("ffmpeg exited with code 1"), /rendering stopped/i);
assert.match(plainRunFailureMessage("ENOENT: manifest.json"), /file could not be found/i);
assert.match(plainRunFailureMessage("critic timeout after 300000ms"), /safety limit/i);
assert.match(plainRunFailureMessage("unexpected low-level failure"), /technical details/i);

console.log("run-status-copy.test.ts: all assertions passed");
