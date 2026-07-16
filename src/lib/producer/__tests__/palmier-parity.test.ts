import assert from "node:assert/strict";
import {
  groupedParityFindings,
  palmierFindingFidelity,
  palmierParityBlock,
  palmierMirrorReady,
  palmierParityState,
  palmierParitySummaryText,
  palmierParityIssueCount,
  type PalmierParity,
} from "../../../components/producer/editor/palmier-parity";

function summary(exact: number, baked = 0, approximate = 0, unsupported = 0) {
  const byStatus = {
    exact: { findings: exact > 0 ? 1 : 0, entries: exact },
    baked: { findings: baked > 0 ? 1 : 0, entries: baked },
    approximate: { findings: approximate > 0 ? 1 : 0, entries: approximate },
    unsupported: { findings: unsupported > 0 ? 1 : 0, entries: unsupported },
  };
  return {
    findings: Object.values(byStatus).reduce((total, value) => total + value.findings, 0),
    entries: exact + baked + approximate + unsupported,
    byStatus,
  };
}

const exact: PalmierParity = {
  fullyEditable: true,
  summary: summary(4),
  findings: [],
};
assert.equal(palmierParityState(exact).fullyEditable, true);
assert.equal(palmierParityState(exact).label, "Fully editable");
assert.equal(palmierParityBlock(exact), null);
assert.equal(palmierParitySummaryText(exact), "4 exact · 0 baked · 0 approximate · 0 unsupported");

const baked: PalmierParity = {
  fullyEditable: false,
  mirrorReady: true,
  summary: summary(3, 2),
  findings: [{
    id: "graphics-baked",
    lane: "graphics",
    status: "baked",
    label: "Motion graphic",
    message: "Pixels transfer, internal controls do not.",
  }],
};
assert.equal(palmierParityState(baked).tone, "partial");
assert.equal(palmierMirrorReady(baked), true);
assert.equal(palmierParityBlock(baked), null, "editability limits do not block an exact mirror");
assert.equal(palmierFindingFidelity(baked.findings[0]), "baked");
assert.equal(palmierParityIssueCount(baked), 2);

const grouped = groupedParityFindings({
  fullyEditable: false,
  summary: summary(1, 0, 0, 2),
  findings: [
    { id: "cut", lane: "cuts", status: "exact", label: "Cut", message: "native" },
    { id: "r1", lane: "motion", status: "unsupported", label: "Ramp 1", message: "no adapter" },
    { id: "r2", lane: "motion", status: "unsupported", label: "Ramp 2", message: "no adapter" },
  ],
});
assert.equal(grouped.length, 1, "exact rows are hidden and repeated issues collapse");
assert.equal(grouped[0].count, 2);

const inconsistent: PalmierParity = {
  fullyEditable: true,
  mirrorReady: false,
  summary: summary(2, 0, 0, 1),
  findings: [{
    id: "unknown:newLane",
    lane: "newLane",
    status: "unsupported",
    label: "newLane",
    message: "Unknown plan lane",
    blocksSync: true,
  }],
};
assert.equal(palmierParityState(inconsistent).fullyEditable, false, "summary fails closed");
assert.equal(palmierParityState(inconsistent).tone, "blocked");
assert.match(palmierParityBlock(inconsistent) ?? "", /mirror is unsafe/);

assert.equal(palmierParityState(undefined).tone, "missing");
assert.match(palmierParityBlock(undefined) ?? "", /report is unavailable/);

console.log("palmier-parity.test.ts: all assertions passed");
