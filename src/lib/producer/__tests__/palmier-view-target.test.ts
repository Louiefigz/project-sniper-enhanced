import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { loadViewTarget } from "../../../app/api/producer/palmier/view/target";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "palmier-view-"));
const projectPath = path.join(root, "demo.palmier");
fs.mkdirSync(projectPath);

function write(state: Record<string, unknown>) {
  fs.writeFileSync(path.join(root, "palmier.sync.json"), JSON.stringify(state));
}

write({
  schemaVersion: 4,
  ownership: "sniper",
  workspaceMode: "managed-draft",
  projectPath,
  latestTimelineId: "draft-1",
  draft: { assetKind: "saved-cut" },
});
const draft = loadViewTarget(root);
assert.ok(!("error" in draft));
if (!("error" in draft)) {
  assert.equal(draft.kind, "working-draft");
  assert.equal(draft.verified, false);
  assert.equal(draft.ownership, "sniper");
  assert.equal(draft.workingAssetKind, "saved-cut");
}

write({
  schemaVersion: 4,
  ownership: "sniper",
  workspaceMode: "verified-mirror",
  mirrorMode: "visual-master",
  projectPath,
  latestTimelineId: "verified-1",
  verification: { ok: true, timelineId: "verified-1" },
});
const verified = loadViewTarget(root);
assert.ok(!("error" in verified));
if (!("error" in verified)) {
  assert.equal(verified.kind, "verified-mirror");
  assert.equal(verified.verified, true);
}

fs.writeFileSync(path.join(root, "palmier.timeline-authority.json"), JSON.stringify({
  schemaVersion: 1,
  origin: "sniper-bootstrap",
  projectId: "managed-project",
  timelineId: "older-bootstrap",
}));
write({
  schemaVersion: 4,
  ownership: "sniper",
  workspaceMode: "verified-mirror",
  mirrorMode: "visual-master",
  projectId: "managed-project",
  projectPath,
  latestTimelineId: "verified-2",
  verification: { ok: true, timelineId: "verified-2" },
});
const verifiedAfterBootstrap = loadViewTarget(root);
assert.ok(!("error" in verifiedAfterBootstrap));
if (!("error" in verifiedAfterBootstrap)) {
  assert.equal(verifiedAfterBootstrap.kind, "verified-mirror");
  assert.equal(verifiedAfterBootstrap.timelineId, "verified-2");
}
fs.rmSync(path.join(root, "palmier.timeline-authority.json"));

write({
  schemaVersion: 4,
  ownership: "palmier",
  mirrorMode: "visual-master",
  projectPath,
  latestTimelineId: "old-1",
});
const previous = loadViewTarget(root);
assert.ok(!("error" in previous));
if (!("error" in previous)) {
  assert.equal(previous.kind, "previous-mirror");
  assert.equal(previous.ownership, "palmier");
  assert.equal(previous.verified, false);
}

fs.writeFileSync(path.join(root, "palmier.timeline-authority.json"), JSON.stringify({
  schemaVersion: 1,
  origin: "palmier-manual",
  projectId: "managed-project",
  timelineId: "manual-head",
  fingerprint: "f".repeat(64),
}));
write({
  schemaVersion: 4,
  ownership: "palmier",
  mirrorMode: "visual-master",
  projectId: "managed-project",
  projectPath,
  latestTimelineId: "old-1",
});
const working = loadViewTarget(root);
assert.ok(!("error" in working));
if (!("error" in working)) {
  assert.equal(working.kind, "working-head");
  assert.equal(working.timelineId, "manual-head");
  assert.equal(working.verified, false);
}

fs.writeFileSync(path.join(root, "palmier.timeline-candidate.json"), JSON.stringify({
  schemaVersion: 1,
  status: "edited",
  projectId: "managed-project",
  timelineId: "candidate-1",
  qc: { status: "pending", approved: false },
}));
const candidate = loadViewTarget(root);
assert.ok(!("error" in candidate));
if (!("error" in candidate)) {
  assert.equal(candidate.kind, "pending-candidate");
  assert.equal(candidate.timelineId, "candidate-1");
  assert.equal(candidate.verified, false);
}
fs.writeFileSync(path.join(root, "palmier.timeline-candidate.json"), JSON.stringify({
  schemaVersion: 1,
  status: "quarantined",
  projectId: "managed-project",
  timelineId: "candidate-1",
  base: {
    projectId: "managed-project",
    timelineId: "manual-head",
    fingerprint: "f".repeat(64),
  },
}));
const quarantine = loadViewTarget(root);
assert.ok(!("error" in quarantine));
if (!("error" in quarantine)) {
  assert.equal(quarantine.kind, "quarantined-candidate");
  assert.equal(quarantine.timelineId, "manual-head");
  assert.equal(quarantine.verified, false);
}
fs.writeFileSync(path.join(root, "palmier.timeline-candidate.json"), JSON.stringify({
  schemaVersion: 1,
  status: "quarantined-recovered",
  projectId: "managed-project",
  timelineId: "candidate-legacy",
  base: {
    projectId: "managed-project",
    timelineId: "manual-head",
    fingerprint: "f".repeat(64),
  },
}));
const legacyRecovery = loadViewTarget(root);
assert.ok(!("error" in legacyRecovery));
if (!("error" in legacyRecovery)) {
  assert.equal(legacyRecovery.kind, "quarantined-candidate");
  assert.equal(legacyRecovery.timelineId, "manual-head");
}
fs.rmSync(path.join(root, "palmier.timeline-candidate.json"));

write({ schemaVersion: 4, ownership: "sniper", projectPath });
assert.ok("error" in loadViewTarget(root));

fs.rmSync(root, { recursive: true, force: true });
console.log("palmier-view-target.test.ts: all assertions passed");
