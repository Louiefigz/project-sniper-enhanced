import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { projectPalmierState } from "../project-palmier-state";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "project-palmier-state-"));
const projectPath = path.join(root, "project.palmier");
fs.mkdirSync(projectPath);
const sidecarPath = path.join(root, "palmier.sync.json");
const authorityPath = path.join(root, "palmier.timeline-authority.json");
const candidatePath = path.join(root, "palmier.timeline-candidate.json");
const write = (filePath: string, value: object) => fs.writeFileSync(filePath, JSON.stringify(value));

try {
  assert.equal(projectPalmierState(root).state, "no_workspace");
  const base = {
    schemaVersion: 4,
    ownership: "sniper",
    projectId: "project-1",
    projectPath,
    latestTimelineId: "timeline-1",
  };
  write(sidecarPath, { ...base, workspaceMode: "managed-draft", draft: { assetKind: "source" } });
  assert.equal(projectPalmierState(root).state, "source_bootstrap");
  const promoted = {
    schemaVersion: 1,
    origin: "sniper-promoted",
    projectId: "project-1",
    timelineId: "edited-1",
    fingerprint: "a".repeat(64),
    approvalCurrent: true,
    readbackCoverage: { complete: true },
    workingHead: {
      projectId: "project-1", timelineId: "edited-1", fingerprint: "a".repeat(64),
    },
    approvedHead: {
      projectId: "project-1", timelineId: "edited-1", fingerprint: "a".repeat(64),
      qcApprovalDigest: "b".repeat(64), exportHash: "c".repeat(64),
    },
  };
  write(authorityPath, promoted);
  const approvedWorking = projectPalmierState(root);
  assert.equal(approvedWorking.state, "approved_working_head");
  assert.equal(approvedWorking.timelineId, "edited-1");
  assert.equal(approvedWorking.verified, true);
  write(authorityPath, { ...promoted, readbackCoverage: { complete: false } });
  assert.equal(projectPalmierState(root).state, "source_bootstrap");
  fs.rmSync(authorityPath);
  write(sidecarPath, { ...base, workspaceMode: "managed-draft", draft: { assetKind: "saved-cut" } });
  assert.equal(projectPalmierState(root).state, "saved_cut");
  write(sidecarPath, {
    ...base,
    workspaceMode: "verified-mirror",
    mirrorMode: "visual-master",
    verification: { ok: true, timelineId: "timeline-1" },
  });
  assert.equal(projectPalmierState(root).state, "approved_mirror");
  write(authorityPath, {
    schemaVersion: 1,
    origin: "sniper-bootstrap",
    projectId: "project-1",
    timelineId: "older-bootstrap",
  });
  assert.equal(projectPalmierState(root).state, "approved_mirror");
  write(authorityPath, {
    schemaVersion: 1,
    origin: "palmier-manual",
    projectId: "project-1",
    timelineId: "manual-1",
  });
  assert.equal(projectPalmierState(root).state, "manual_working_head");
  write(candidatePath, {
    schemaVersion: 1,
    status: "edited",
    projectId: "project-1",
    timelineId: "candidate-1",
    qc: { status: "pending", approved: false },
  });
  const pending = projectPalmierState(root);
  assert.equal(pending.state, "pending_candidate");
  assert.equal(pending.timelineId, "candidate-1");
  write(candidatePath, {
    schemaVersion: 1,
    status: "quarantined",
    projectId: "project-1",
    timelineId: "candidate-1",
    base: { projectId: "project-1", timelineId: "manual-1", fingerprint: "a".repeat(64) },
  });
  const quarantined = projectPalmierState(root);
  assert.equal(quarantined.state, "quarantined_candidate");
  assert.equal(quarantined.timelineId, "manual-1");
  write(candidatePath, {
    schemaVersion: 1,
    status: "quarantined-recovered",
    projectId: "project-1",
    timelineId: "candidate-1",
  });
  const legacyRecovered = projectPalmierState(root);
  assert.equal(legacyRecovered.state, "quarantined_candidate");
  assert.equal(legacyRecovered.candidateQc?.canDiscard, true);
  fs.rmSync(candidatePath);
  fs.rmSync(authorityPath);
  write(sidecarPath, { ...base, mirrorMode: "visual-master" });
  assert.equal(projectPalmierState(root).state, "previous_export");
  write(sidecarPath, { schemaVersion: 4, projectPath });
  assert.equal(projectPalmierState(root).state, "unavailable");
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}

console.log("project-palmier-state.test.ts: all assertions passed");
