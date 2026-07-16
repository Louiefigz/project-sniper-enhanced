import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  PALMIER_CANDIDATE_FILE,
  PALMIER_NATIVE_QC_FILE,
  PALMIER_NATIVE_QC_RUN_FILE,
  assertCandidateSlotAvailable,
  currentApprovedCandidate,
  palmierCandidateQcState,
} from "../../server/palmier-candidate-qc";
import {
  candidateActionLabel,
  candidateActionTitle,
} from "../candidate-qc-action";
import { projectPalmierState } from "../../server/project-palmier-state";
import { captureProcessIdentity } from "../../server/process-liveness";
import { runTestPalmierNativeEdit } from "./palmier-native-test-fixture";

function writeJson(filePath: string, value: unknown): void {
  writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

function sha(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function fixture(root: string): { dir: string; candidate: Record<string, unknown>; qc: Record<string, unknown> } {
  const dir = path.join(root, "producer");
  const palmierProject = path.join(root, "project.palmier");
  mkdirSync(dir, { recursive: true });
  writeFileSync(palmierProject, "project");
  writeJson(path.join(dir, "palmier.sync.json"), {
    schemaVersion: 4,
    projectPath: palmierProject,
    projectId: "project-1",
    latestTimelineId: "parent-1",
    workspaceMode: "verified-mirror",
    mirrorMode: "visual-master",
  });
  writeJson(path.join(dir, "palmier.timeline-authority.json"), {
    schemaVersion: 1,
    authority: "palmier",
    projectId: "project-1",
    timelineId: "parent-1",
    fingerprint: "a".repeat(64),
    origin: "palmier-manual",
    approvalCurrent: false,
    approvedHead: { timelineId: "approved-old", fingerprint: "c".repeat(64) },
  });
  const candidate = {
    schemaVersion: 1,
    status: "qc-approved",
    projectId: "project-1",
    timelineId: "candidate-1",
    fingerprint: "b".repeat(64),
    qc: { approved: true, approvalDigest: "approval-1" },
  };
  const exportPath = path.join(dir, "palmier.candidate.mp4");
  writeFileSync(exportPath, "candidate-export");
  const qc = {
    schemaVersion: 1,
    status: "qc-approved",
    approvalDigest: "approval-1",
    candidate: { timelineId: "candidate-1", fingerprint: "b".repeat(64) },
    export: { path: exportPath, hash: sha("candidate-export") },
  };
  writeJson(path.join(dir, PALMIER_CANDIDATE_FILE), candidate);
  writeJson(path.join(dir, PALMIER_NATIVE_QC_FILE), qc);
  return { dir, candidate, qc };
}

async function guardedSecondAsk(dir: string): Promise<void> {
  let cliCalls = 0;
  let modelCalls = 0;
  const authority = {
    schemaVersion: 1, authority: "palmier", origin: "palmier-manual",
    projectId: "project-1", timelineId: "parent-1", fingerprint: "a".repeat(64),
    readbackCoverage: { complete: true },
    timeline: { id: "parent-1", totalFrames: 100, tracks: [] },
  };
  writeJson(path.join(dir, "palmier.timeline-authority.json"), authority);
  const beforeCandidate = readFileSync(path.join(dir, PALMIER_CANDIDATE_FILE));
  const beforeQc = readFileSync(path.join(dir, PALMIER_NATIVE_QC_FILE));
  await assert.rejects(runTestPalmierNativeEdit({
    dir, request: "Make a second change", scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex: async () => { modelCalls += 1; return {}; },
    cli: async () => {
      cliCalls += 1;
      return { ok: true, status: "reconciled", authority };
    },
  }), /Discard candidate & keep parent/);
  assert.equal(cliCalls, 1, "the second Ask may reconcile manual truth but must never fork");
  assert.equal(modelCalls, 0, "the second Ask must stop before planning");
  assert.deepEqual(readFileSync(path.join(dir, PALMIER_CANDIDATE_FILE)), beforeCandidate);
  assert.deepEqual(readFileSync(path.join(dir, PALMIER_NATIVE_QC_FILE)), beforeQc);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-candidate-qc-ts-"));
  try {
    const { dir, qc } = fixture(root);
    assert.ok(currentApprovedCandidate(dir, "project-1"));
    assert.equal(palmierCandidateQcState(dir).state, "approved");
    assert.equal(palmierCandidateQcState(dir).canDiscard, true);
    assert.equal(projectPalmierState(dir).state, "approved_candidate");

    writeJson(path.join(dir, PALMIER_NATIVE_QC_FILE), { ...qc, approvalDigest: "stale" });
    assert.equal(currentApprovedCandidate(dir, "project-1"), null);
    assert.equal(palmierCandidateQcState(dir).state, "stale");
    const stale = projectPalmierState(dir);
    assert.equal(stale.state, "pending_candidate");
    assert.equal(stale.candidateApprovalStale, true);
    assert.equal(stale.candidateQc?.canRunQc, false);
    assert.equal(stale.candidateQc?.canDiscard, true);
    assert.throws(() => assertCandidateSlotAvailable(dir), /Use the approved candidate/);
    await guardedSecondAsk(dir);

    writeFileSync(path.join(dir, "palmier.candidate.mp4"), "changed-export");
    writeJson(path.join(dir, PALMIER_NATIVE_QC_FILE), qc);
    assert.equal(currentApprovedCandidate(dir, "project-1"), null,
      "stat-signature changes must invalidate the cached export hash");

    writeJson(path.join(dir, PALMIER_CANDIDATE_FILE), {
      schemaVersion: 1, status: "edited", projectId: "project-1",
      timelineId: "candidate-2", fingerprint: "d".repeat(64),
    });
    assert.throws(() => assertCandidateSlotAvailable(dir), /already edited/);
    await guardedSecondAsk(dir);
    writeJson(path.join(dir, PALMIER_CANDIDATE_FILE), {
      schemaVersion: 1, status: "quarantined-recovered", projectId: "project-1",
      timelineId: "candidate-legacy", fingerprint: "e".repeat(64),
      base: { projectId: "project-1", timelineId: "parent-1", fingerprint: "a".repeat(64) },
      recovery: { status: "restored" },
    });
    assert.throws(() => assertCandidateSlotAvailable(dir), /archive the failure/,
      "legacy recovery without an evidence archive must keep the slot blocked");
    const legacy = palmierCandidateQcState(dir);
    assert.equal(legacy.state, "quarantined");
    assert.equal(legacy.canDiscard, true);
    assert.equal(projectPalmierState(dir).state, "quarantined_candidate");

    writeJson(path.join(dir, PALMIER_CANDIDATE_FILE), {
      schemaVersion: 1, status: "edited", projectId: "project-1",
      timelineId: "candidate-2", fingerprint: "d".repeat(64),
    });
    const now = new Date().toISOString();
    writeJson(path.join(dir, PALMIER_NATIVE_QC_RUN_FILE), {
      schemaVersion: 1, status: "running", action: "run_qc",
      pid: process.pid, ownerIdentity: captureProcessIdentity(process.pid),
      updatedAt: now, step: "composition", message: "Reviewing composition.",
      log: [{ at: now, step: "composition", message: "Reviewing composition." }],
    });
    const running = palmierCandidateQcState(dir);
    assert.equal(running.run.active, true);
    assert.equal(running.run.action, "run_qc");
    assert.equal(running.run.step, "composition");
    assert.equal(running.canRunQc, false);
    assert.equal(candidateActionLabel("run_qc"), "Running candidate QC…");
    assert.equal(candidateActionLabel("promote"), "Promoting approved candidate…");
    assert.equal(candidateActionLabel("discard"), "Archiving candidate & restoring parent…");
    assert.match(candidateActionTitle("discard"), /Palmier stays locked/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("palmier-candidate-qc.test.ts: all assertions passed");
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
