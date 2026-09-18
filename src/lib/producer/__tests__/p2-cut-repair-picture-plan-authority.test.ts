import assert from "node:assert/strict";
import {
  assertCutRepairPicturePlanParent,
  bindCutRepairPicturePlanAuthority,
  parseCutRepairPicturePlanAuthorityV1,
} from "@/lib/producer/contracts/cut-repair-picture-plan-authority";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import { parsePreparedMediaResult } from
  "@/app/api/producer/ai-edit/cut-repair-preparation-plan";
import type { ProjectRevisionV2 } from
  "@/lib/producer/contracts/project-revision";
import { cutRestoreAction, fixtureSha } from "./_cut-restore-speech-fixture";
import {
  pictureFixture,
  picturePreparedMedia,
  sealPictureAuthority,
  type PictureFixture,
} from "./_p2-cut-repair-picture-fixture";

function assertParentBinding(value: PictureFixture): void {
  const bound = bindCutRepairPicturePlanAuthority(
    value.plan, value.operation, value.childTimelineMapHash);
  const parent: ProjectRevisionV2 = {
    schemaVersion: 2,
    parentRevisionHash: null,
    planObjectHash: fixtureSha("c"),
    planContentHash: fixtureSha("0"),
    manifestHash: fixtureSha("1"),
    sourceSnapshotSetHash: fixtureSha("2"),
    transcriptTimingHash: fixtureSha("3"),
    timelineMapHash: value.operation.parentTimelineMapHash,
    canvasProfileHash: fixtureSha("4"),
    destinationProfileHashes: [],
    pictureLockHash: value.operation.parentPictureLockHash,
    workflowState: "PICTURE_LOCKED",
    requestLedgerHash: fixtureSha("5"),
    renderGraphHash: fixtureSha("6"),
    projectionReceiptHash: null,
    authoritativeSidecars: {},
  };
  assert.doesNotThrow(() => assertCutRepairPicturePlanParent(
    bound, value.operation, parent));
  assert.throws(() => assertCutRepairPicturePlanParent(
    bound, value.operation,
    { ...parent, planObjectHash: fixtureSha("d") }),
  /does not bind parent authority/);
}

function assertTamperFailures(value: PictureFixture): void {
  const wrongRow = structuredClone(value.plan);
  wrongRow.cutTrack = [
    (value.authority.parentCutRow as Record<string, unknown>)];
  assert.throws(() => bindCutRepairPicturePlanAuthority(
    wrongRow, value.operation, value.childTimelineMapHash),
  /does not bind the review plan/);

  const missing = structuredClone(value.plan);
  delete missing.cutRepairPicturePlanAuthority;
  assert.throws(() => bindCutRepairPicturePlanAuthority(
    missing, value.operation, value.childTimelineMapHash),
  /lacks picture-plan authority/);

  const invalidCore = structuredClone(value.authority);
  delete invalidCore.authorityHash;
  invalidCore.reversion = {
    ...(invalidCore.reversion as Record<string, unknown>),
    segmentId: "seg-foreign",
  };
  assert.throws(
    () => parseCutRepairPicturePlanAuthorityV1(
      sealPictureAuthority(invalidCore)),
    /row or reversion binding is stale/);

  const audio = parseCutRestoreSpeechV1(cutRestoreAction());
  assert.throws(() => bindCutRepairPicturePlanAuthority(
    value.plan, audio, value.childTimelineMapHash),
  /audio-only repair plan carries picture authority/);
}

function assertPreparedBinding(value: PictureFixture): void {
  const prepared = picturePreparedMedia(value);
  const parsed = parsePreparedMediaResult(prepared);
  assert.equal(
    parsed.picturePlanAuthority?.authorityHash,
    value.authority.authorityHash);
  assert.deepEqual(parsed.preparedMedia, prepared);
  assert.throws(
    () => parsePreparedMediaResult({ ...prepared, injected: true }),
    /unsupported fields/);
}

function run(): void {
  const value = pictureFixture();
  const bound = bindCutRepairPicturePlanAuthority(
    value.plan, value.operation, value.childTimelineMapHash);
  assert.equal(bound?.authorityHash, value.authority.authorityHash);
  assert.deepEqual(parseCutRepairPicturePlanAuthorityV1(
    value.authority), value.authority);
  assertParentBinding(value);
  assertTamperFailures(value);
  assertPreparedBinding(value);
}

run();
console.log("p2-cut-repair-picture-plan-authority tests passed");
