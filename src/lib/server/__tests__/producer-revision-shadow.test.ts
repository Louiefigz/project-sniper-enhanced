import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { compileTypedCompatibilityEdit } from
  "@/app/api/producer/ai-edit/typed-compatibility-edit";
import type { TypedCompatibilityEdit } from
  "@/app/api/producer/ai-edit/typed-compatibility-edit";
import { applySetGraphicTextV1, parseSetGraphicTextV1 } from
  "@/lib/producer/set-graphic-text-v1";
import { compatibilityPlanHash } from
  "@/app/api/producer/auto-edit/compatibility-picture-identity";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import { writeContentAddressedJsonSync } from "../content-addressed-json";
import { resolveProducerAuthorityHeadSync } from "../producer-revision-head";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "../producer-authority-files";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { runTypedCompatibilityShadowSync } from "../producer-revision-shadow";

const hash = (value: string): string => value.repeat(64);
const sha256 = (bytes: Buffer | string): string =>
  createHash("sha256").update(bytes).digest("hex");
const parent: EditPlan = {
  planVersion: 1,
  target: { mode: "longform" },
  cutTrack: [{ sourceId: "source-a", start: 0, end: 60 }],
  graphicsTrack: [{
    id: "g-00000001",
    kind: "statement-card",
    outStart: 45,
    outEnd: 51,
    anchor: "own-screen",
    spec: { text: "Old copy" },
  }],
};
const child: EditPlan = {
  ...parent,
  planVersion: 2,
  graphicsTrack: [{
    ...parent.graphicsTrack![0],
    spec: { text: "New copy" },
  }],
};

const root = fs.realpathSync(
  fs.mkdtempSync(path.join(os.tmpdir(), "sniper-shadow-live-")),
);
try {
  const producerDir = path.join(root, "producer");
  fs.mkdirSync(producerDir);
  const manifestPath = path.join(root, "asset_manifest.json");
  fs.writeFileSync(manifestPath, "{}\n");
  const manifestHash = sha256(fs.readFileSync(manifestPath));
  const parentText = `${JSON.stringify(parent, null, 1)}\n`;
  const childBytes = Buffer.from(`${JSON.stringify(child, null, 1)}\n`);
  const cutTrackDigest = canonicalJsonSha256(parent.cutTrack);
  const cutDecisionsDigest = canonicalJsonSha256({});
  const lock = writeContentAddressedJsonSync(
    path.join(producerDir, "picture_locks"),
    {
      schemaVersion: 1,
      kind: "compatibility-picture-lock",
      adapterVersion: 1,
      approvedCutPlanHash: hash("1"),
      planContentHash: compatibilityPlanHash(
        parent as Record<string, unknown>,
        cutTrackDigest,
        cutDecisionsDigest,
      ),
      manifestHash,
      transcriptDigest: hash("2"),
      cutTrackDigest,
      cutDecisionsDigest,
      cutApprovalReceiptHash: hash("3"),
      cutReviewApprovalReceiptHash: hash("4"),
      cutReviewAuthorityDigest: hash("5"),
      cutAuthorityDigest: hash("6"),
      projectionReceiptHash: hash("7"),
      timelineMapHash: hash("8"),
      qualityPolicyVersion: 1,
      requiredCleanReviews: 2,
    },
  );
  assert.throws(() => compileTypedCompatibilityEdit(parent, {
    ...child,
    planVersion: 1,
  }), /retired/);
  // Historical TEST DTO exercises shadow storage only; no new visual edit is admitted.
  const operation = parseSetGraphicTextV1({
    schemaVersion: 1, operation: "SetGraphicTextV1",
    target: { lane: "graphicsTrack", id: "g-00000001" },
    text: "New copy", expectedCurrentText: "Old copy",
  });
  assert.throws(() => applySetGraphicTextV1(parent, operation), /retired/);
  const typed: TypedCompatibilityEdit = {
    adapterVersion: 1, kind: "set-graphic-text", operation,
    operationHash: canonicalJsonSha256(operation),
  };
  assert.equal(typed?.operation.target.id, "g-00000001");
  assert.equal(
    child.graphicsTrack?.[0].outStart,
    parent.graphicsTrack?.[0].outStart,
    "historical TEST plans retain the authored start time",
  );
  assert.equal(
    child.graphicsTrack?.[0].outEnd,
    parent.graphicsTrack?.[0].outEnd,
    "historical TEST plans retain the authored end time",
  );
  assert.deepEqual(child.cutTrack, parent.cutTrack);
  assert.deepEqual(child.target, parent.target);
  const input = {
    producerDir,
    manifestPath,
    parentPlanText: parentText,
    parentPlanHash: sha256(parentText),
    childPlanBytes: childBytes,
    childPlanHash: sha256(childBytes),
    rawIntent: "Change only the right statement-card copy.",
    requestId: "10000000-0000-4000-8000-000000000001",
    submittedAt: "2026-07-29T12:00:00.000Z",
    typedEdit: typed!,
  };
  const committed = runTypedCompatibilityShadowSync(input);
  assert.equal(committed.status, "committed");
  if (committed.status !== "committed") throw new Error("expected commit");
  const head = resolveProducerAuthorityHeadSync(producerDir);
  assert.equal(head, committed.childRevisionHash);
  const paths = producerAuthorityPaths(producerDir);
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions,
    head,
  ));
  assert.equal(revision.planContentHash, planObjectContentHash(child));
  assert.equal(
    revision.authoritativeSidecars.renderedPlanFile,
    input.childPlanHash,
  );
  assert.equal(revision.pictureLockHash, lock.hash);
  assert.equal(revision.workflowState, "TREATMENT_DRAFT");
  const replay = runTypedCompatibilityShadowSync(input);
  assert.equal(replay.status, "replayed");

  const missingIdentity = runTypedCompatibilityShadowSync({
    ...input,
    requestId: undefined,
  });
  assert.equal(missingIdentity.status, "skipped-unqualified");
  const mismatchedManifest = path.join(root, "foreign-manifest.json");
  fs.writeFileSync(mismatchedManifest, "{\"foreign\":true}\n");
  const skipped = runTypedCompatibilityShadowSync({
    ...input,
    producerDir: path.join(root, "other-producer"),
    manifestPath: mismatchedManifest,
  });
  assert.equal(skipped.status, "skipped-unqualified");
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}

console.log("producer-revision-shadow tests passed");
