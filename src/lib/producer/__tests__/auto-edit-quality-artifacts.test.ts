import assert from "node:assert/strict";
import {
  existsSync, mkdtempSync, readFileSync, renameSync, rmSync, symlinkSync,
  unlinkSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  approvalPath,
  candidateFinalPath,
  copyAuditInputs,
  prepareQcRound,
  promoteApprovedCandidate,
  readApproval,
} from "../../server/auto-edit-quality-artifacts";
import { fileSha256 } from "../../server/auto-edit-job-store";
import { planContentHash } from "../../server/auto-edit-authority";
import { writeApprovalFixture } from "./auto-edit-approval-fixture";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-qc-artifacts-"));
try {
  const producer = path.join(root, "producer");
  const roundDir = prepareQcRound(producer, "token:unsafe/path", 2);
  assert.ok(roundDir.startsWith(path.join(producer, ".sniper-qc")));
  assert.ok(!roundDir.includes("token:unsafe/path"));

  writeFileSync(path.join(producer, "edit_plan.json"), '{"planVersion":1,"cutTrack":[]}');
  writeFileSync(path.join(producer, "manifest.json"), '{"sources":[]}');
  for (const name of ["timeline_map.json", "cover.png"]) writeFileSync(path.join(producer, name), name);
  copyAuditInputs(producer, roundDir);
  assert.equal(readFileSync(path.join(roundDir, "edit_plan.json"), "utf8"), '{"planVersion":1,"cutTrack":[]}');

  const candidate = candidateFinalPath(producer, "token:unsafe/path", 2);
  writeFileSync(candidate, "candidate-video");
  const candidateHash = fileSha256(candidate)!;
  writeFileSync(`${candidate}.assembled.json`, JSON.stringify({
    planHash: planContentHash(path.join(producer, "edit_plan.json")), authorityHash: candidateHash,
  }));
  writeFileSync(candidate.replace(/\.mp4$/, ".proxy.mp4"), "candidate-proxy");
  writeFileSync(path.join(roundDir, "audit_report.json"), "candidate-audit");
  const record = writeApprovalFixture({
    ctx: {
      dir: producer, scope: "light", planPath: path.join(producer, "edit_plan.json"),
      manifestPath: path.join(producer, "manifest.json"), transcriptsDir: producer,
    },
    token: "token:unsafe/path", candidate, qcRound: 2,
  });
  promoteApprovedCandidate(candidate, producer, record);

  assert.equal(readFileSync(path.join(producer, "final.mp4"), "utf8"), "candidate-video");
  assert.equal(
    JSON.parse(readFileSync(path.join(producer, "final.mp4.assembled.json"), "utf8")).authorityHash,
    candidateHash,
  );
  assert.equal(readFileSync(path.join(producer, "final.proxy.mp4"), "utf8"), "candidate-proxy");
  assert.ok(existsSync(approvalPath(producer)));
  assert.equal(JSON.parse(readFileSync(approvalPath(producer), "utf8")).finalHash, candidateHash);
  assert.ok(readApproval(producer));
  const packetBytes = readFileSync(record.planningReviews[0].packet.path, "utf8");
  writeFileSync(record.planningReviews[0].packet.path, '{"tampered":true}');
  assert.equal(readApproval(producer), null);
  writeFileSync(record.planningReviews[0].packet.path, packetBytes);
  assert.ok(readApproval(producer));
  const packetDir = path.dirname(record.planningReviews[0].packet.path);
  const movedPacketDir = `${packetDir}-real`;
  renameSync(packetDir, movedPacketDir);
  symlinkSync(movedPacketDir, packetDir, "dir");
  assert.equal(readApproval(producer), null);
  unlinkSync(packetDir);
  renameSync(movedPacketDir, packetDir);
  assert.ok(readApproval(producer));
  writeFileSync(record.renderedReviews[0].path, '{"tampered":true}');
  assert.equal(readApproval(producer), null);

  const unproven = candidateFinalPath(producer, "unproven", 3);
  prepareQcRound(producer, "unproven", 3);
  writeFileSync(unproven, "unproven-video");
  assert.throws(() => promoteApprovedCandidate(unproven, producer, record), /authority proof is missing/);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("auto-edit-quality-artifacts.test.ts: all assertions passed");
