import assert from "node:assert/strict";
import {
  parseCutRepairRippleImpactV1,
  rippleAffectedDependentIds,
} from "@/lib/producer/contracts/cut-repair-ripple-impact";
import { parseCutRepairRippleReopenReceiptV1 } from
  "@/lib/producer/contracts/cut-repair-ripple-reopen";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  loadCutRepairRippleReopenActionSync,
  recoverCutRepairRippleReopenSync,
  reopenCutRepairForRippleSync,
} from "../cut-repair-ripple-reopen-store";
import type { CutRepairTransitionBoundary } from
  "../cut-repair-transition-model";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "../producer-authority-files";
import { resolveProducerAuthorityHeadSync } from "../producer-revision-head";
import {
  cleanReopenFixture,
  createReopenFixture,
  REOPEN_PLAN,
} from "./_p2-cut-repair-ripple-reopen-fixture";

const BOUNDARIES: CutRepairTransitionBoundary[] = [
  "after-materialized",
  "after-receipt-proved",
  "after-local-commit-intent",
  "after-advance",
  "after-head",
  "after-committed",
];

function childRevision(
  producer: string,
  childRevisionHash: string,
) {
  const paths = producerAuthorityPaths(producer);
  return parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, childRevisionHash));
}

function basicReopenPreservesAuthority(): void {
  const value = createReopenFixture("1");
  try {
    const result = reopenCutRepairForRippleSync({
      producerDir: value.producer, action: value.action,
    });
    assert.equal(result.status, "committed");
    assert.ok(result.receiptHash);
    const child = childRevision(value.producer, result.childRevisionHash);
    assert.equal(child.workflowState, "CUT_DRAFT");
    assert.equal(child.pictureLockHash, null);
    assert.equal(child.planContentHash, value.action.preservedPlanContentHash);
    assert.equal(child.timelineMapHash, value.action.preservedTimelineMapHash);
    assert.equal(child.renderGraphHash, value.action.preservedRenderGraphHash);
    assert.equal(
      child.projectionReceiptHash,
      value.action.preservedProjectionReceiptHash,
    );
    assert.equal(resolveProducerAuthorityHeadSync(value.producer),
      result.childRevisionHash);
    const paths = producerAuthorityPaths(value.producer);
    assert.deepEqual(assertObjectHashSync(
      paths.objects.plans, child.schemaVersion === 2
        ? child.planObjectHash : ""), REOPEN_PLAN);
    const receipt = parseCutRepairRippleReopenReceiptV1(assertObjectHashSync(
      paths.objects.receipts, result.receiptHash!));
    assert.deepEqual(receipt.affectedDependentIds,
      ["graphic-after", "music-after", "caption-crossing"]);
    assert.deepEqual(receipt.unchangedOutputLockedIds,
      ["title-output-locked"]);
  } finally {
    cleanReopenFixture(value);
  }
}

function replayAndSubstitutionAreClosed(): void {
  const value = createReopenFixture("2");
  try {
    const first = reopenCutRepairForRippleSync({
      producerDir: value.producer, action: value.action,
    });
    const replay = reopenCutRepairForRippleSync({
      producerDir: value.producer, action: value.action,
    });
    assert.equal(replay.status, "replayed");
    assert.equal(replay.childRevisionHash, first.childRevisionHash);
    assert.throws(() => recoverCutRepairRippleReopenSync(
      value.producer,
      value.action.idempotencyKey,
      "f".repeat(64),
    ), /target is absent or substituted/);
    assert.throws(() => reopenCutRepairForRippleSync({
      producerDir: value.producer,
      action: { ...value.action, requestedAt: "2026-07-30T12:01:00.000Z" },
    }), /idempotency key belongs to another action/);
  } finally {
    cleanReopenFixture(value);
  }
}

function crashRecoveryIsComplete(): void {
  BOUNDARIES.forEach((boundary, index) => {
    const value = createReopenFixture((index + 3).toString(16));
    try {
      assert.throws(() => reopenCutRepairForRippleSync({
        producerDir: value.producer, action: value.action,
      }, {
        after: (observed) => {
          if (observed === boundary) throw new Error(`crash:${boundary}`);
        },
      }), new RegExp(`crash:${boundary}`));
      const recovered = recoverCutRepairRippleReopenSync(
        value.producer,
        value.action.idempotencyKey,
        value.action.targetHash,
      );
      assert.ok(["committed", "replayed"].includes(recovered.status));
      assert.equal(childRevision(
        value.producer, recovered.childRevisionHash).workflowState, "CUT_DRAFT");
    } finally {
      cleanReopenFixture(value);
    }
  });
}

function nonExactAndDuplicateImpactsFailClosed(): void {
  assert.throws(() => parseCutRepairRippleImpactV1({
    exact: false,
    blockingReason: "NO_ADJACENT_SOURCE_HANDLE",
    reopensPictureLock: true,
  }), /unsupported fields|missing fields/);
  const value = createReopenFixture("a");
  try {
    const impact = parseCutRepairRippleImpactV1(
      value.action.analysis.rippleImpact);
    assert.deepEqual(rippleAffectedDependentIds(impact),
      ["graphic-after", "music-after", "caption-crossing"]);
    assert.throws(() => parseCutRepairRippleImpactV1({
      ...impact,
      invalidatedDependents: ["graphic-after"],
    }), /mutually exclusive/);
    assert.equal(loadCutRepairRippleReopenActionSync(
      value.producer, value.action.idempotencyKey), null);
  } finally {
    cleanReopenFixture(value);
  }
}

basicReopenPreservesAuthority();
replayAndSubstitutionAreClosed();
crashRecoveryIsComplete();
nonExactAndDuplicateImpactsFailClosed();
console.log("p2-cut-repair-ripple-reopen tests passed");
