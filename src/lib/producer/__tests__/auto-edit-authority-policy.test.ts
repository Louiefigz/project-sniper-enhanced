import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import {
  autoEditJobPath,
  fileSha256,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";
import {
  markLegacyQualityPolicy,
  qualityPolicyMarkerPath,
  qualityPolicyRequirement,
  readQualityPolicyMarker,
} from "../../server/auto-edit-quality-policy";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-authority-policy-"));
try {
  const project = path.join(root, "project");
  const dir = path.join(project, "producer");
  const source = path.join(project, "source");
  const reference = path.join(project, "reference");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  mkdirSync(reference, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "manifest.json");
  const transcriptPath = path.join(source, "source.transcript.json");
  const mediaPath = path.join(source, "source.mp4");
  const profilePath = path.join(reference, "style_profile.json");
  const deepStudyPath = path.join(reference, "deep_study.json");
  const framePath = path.join(reference, "frame.jpg");
  writeFileSync(planPath, '{"planVersion":1,"cutTrack":[]}');
  writeFileSync(transcriptPath, '{"transcript":[{"text":"one"}]}');
  writeFileSync(mediaPath, "media-bytes-are-not-directly-hashed");
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{ path: mediaPath, contentHash: "manifest-media-hash", transcriptPath }],
  }));
  writeFileSync(path.join(project, "project.json"), JSON.stringify({
    origin: "raw", history: [], intent: { mode: "short", scope: "produced", lanes: {} },
  }));
  writeFileSync(profilePath, '{"style":"measured"}');
  writeFileSync(deepStudyPath, '{"study":"deep"}');
  writeFileSync(framePath, "reference-frame");
  writeFileSync(path.join(reference, "reference.json"), '{"strategy":"mimic"}');
  writeFileSync(path.join(reference, "fingerprint.json"), '{"sha256":"source"}');
  const ctx: AutoEditCtx = {
    dir, scope: "produced", planPath, manifestPath, transcriptsDir: source,
    intent: { mode: "short", lanes: {} },
    referenceStudy: {
      id: "ref-1", title: "Reference", mode: "short", dir: reference,
      profilePath, deepStudyPath, representativeFrames: [framePath],
    },
  };

  const initial = autoEditAuthoritySnapshot(ctx);
  assert.match(initial.digest, /^[0-9a-f]{64}$/);
  assert.match(initial.pipelineDigest, /^[0-9a-f]{64}$/);
  writeFileSync(mediaPath, "different-media-bytes-same-manifest-authority");
  assert.equal(autoEditAuthoritySnapshot(ctx).digest, initial.digest);
  writeFileSync(transcriptPath, '{"transcript":[{"text":"two"}]}');
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial.digest);
  writeFileSync(transcriptPath, '{"transcript":[{"text":"one"}]}');
  writeFileSync(framePath, "changed-reference-frame");
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial.digest);
  writeFileSync(framePath, "reference-frame");
  writeFileSync(path.join(project, "project.json"), JSON.stringify({
    origin: "raw", history: [], intent: { mode: "short", scope: "full", lanes: {} },
  }));
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial.digest);

  assert.equal(qualityPolicyRequirement(dir).valid, false);
  startAutoEditJob({ ctx, token: "authority", snapshots: 0, bootstrapPlanHash: fileSha256(planPath) });
  assert.equal(readQualityPolicyMarker(dir)?.mode, "managed");
  rmSync(autoEditJobPath(dir), { force: true });
  assert.deepEqual(qualityPolicyRequirement(dir), {
    required: true, legacy: false, valid: true, reason: null,
  });
  writeFileSync(qualityPolicyMarkerPath(dir), "corrupt");
  assert.equal(qualityPolicyRequirement(dir).valid, false);

  const legacy = path.join(root, "legacy");
  mkdirSync(legacy);
  markLegacyQualityPolicy(legacy, "verified pre-policy fixture");
  assert.deepEqual(qualityPolicyRequirement(legacy), {
    required: false, legacy: true, valid: true, reason: null,
  });
  assert.throws(() => markLegacyQualityPolicy(legacy, "again"), /refusing to downgrade/);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("auto-edit-authority-policy.test.ts: all assertions passed");
