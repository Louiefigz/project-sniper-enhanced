import { existsSync } from "node:fs";
import path from "node:path";
import {
  parseCutRepairPromotionActionV1,
  type CutRepairPromotionActionV1,
} from "@/lib/producer/contracts/cut-repair-promotion-transition";
import { parseCutRepairTransitionReceiptV1 } from
  "@/lib/producer/contracts/cut-repair-transition-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  parseCutRepairTransitionRecord,
  recoverCutRepairTransitionSync,
  type CutRepairTransitionHooks,
  type CutRepairTransitionOutcome,
  type CutRepairTransitionRecord,
} from "./cut-repair-transition-store";
import {
  assertObjectHashSync,
  authorityKey,
  producerAuthorityPaths,
  readAuthorityJsonSync,
} from "./producer-authority-files";
import { resolveProducerAuthorityHeadSync } from
  "./producer-revision-head";
import { verifyStoredCutRepairPromotionByHashesSync } from
  "./producer-cut-repair-artifact-verification";
import {
  assertRevisionPlanObjectSync,
} from "./producer-plan-authority";
import { buildLegacyPromotedRevisionV1, buildPromotedRevisionV2 } from
  "./cut-repair-promotion-revision";
import {
  activateCutRepairPromotionMediaSync,
  verifyCutRepairPromotionMediaSync,
} from "./cut-repair-media-activation";
import {
  materializeCutRepairPromotionSync,
  reopenCutRepairPromotionContextSync,
  type CutRepairPromotionTransitionInput,
} from "./cut-repair-promotion-materialize";

export type { CutRepairPromotionTransitionInput } from
  "./cut-repair-promotion-materialize";

function existingRecord(
  producerDir: string,
  action: CutRepairPromotionActionV1,
): CutRepairTransitionRecord | null {
  const paths = producerAuthorityPaths(producerDir);
  const filePath = path.join(
    paths.sagas, "cut-repair-promotion", "records",
    `${authorityKey(action.idempotencyKey)}.json`);
  if (!existsSync(filePath)) return null;
  const record = parseCutRepairTransitionRecord(
    readAuthorityJsonSync(filePath));
  if (record.actionHash !== canonicalJsonSha256(action)) {
    throw new Error("promotion idempotency key is bound to another action");
  }
  return record;
}

function recordById(
  producerDir: string,
  idempotencyKey: string,
): CutRepairTransitionRecord {
  const paths = producerAuthorityPaths(producerDir);
  const filePath = path.join(
    paths.sagas, "cut-repair-promotion", "records",
    `${authorityKey(idempotencyKey)}.json`);
  return parseCutRepairTransitionRecord(readAuthorityJsonSync(filePath));
}

function verifyPromotionRecord(
  producerDir: string,
  record: CutRepairTransitionRecord,
): void {
  if (record.transition !== "promotion") {
    throw new Error("cut repair promotion recovery received another transition");
  }
  const paths = producerAuthorityPaths(producerDir);
  const { value, revision } = reopenCutRepairPromotionContextSync(
    producerDir, record);
  const hashes = record.artifactHashes;
  assertRevisionPlanObjectSync(paths, revision);
  const expected = revision.schemaVersion === 1
    ? buildLegacyPromotedRevisionV1(value, hashes.action)
    : buildPromotedRevisionV2(value, hashes.action, hashes.plan);
  const receipt = parseCutRepairTransitionReceiptV1(assertObjectHashSync(
    paths.objects.receipts, hashes.receipt));
  if (record.actionHash !== hashes.action
      || record.childRevisionHash !== hashes.revision
      || record.receiptHash !== hashes.receipt
      || canonicalJsonSha256(revision) !== canonicalJsonSha256(expected)
      || receipt.actionHash !== hashes.action
      || receipt.childRevisionHash !== hashes.revision
      || receipt.originalPictureLockedParentHash
        !== record.originalPictureLockedParentHash) {
    throw new Error("stored cut repair promotion transition is inconsistent");
  }
  verifyStoredCutRepairPromotionByHashesSync({
    paths, hashes,
    operation: value.reviewAction.operation,
    revision,
    invariantProofHash: value.bindings.invariantProofHash,
  });
}

function assertRecoveryHead(
  producerDir: string,
  record: CutRepairTransitionRecord,
  allowed: readonly string[],
): void {
  const head = resolveProducerAuthorityHeadSync(producerDir);
  if (!allowed.includes(head)) {
    throw new Error(
      "cut repair promotion recovery cannot reactivate stale descendant media",
    );
  }
}

/** Recover a promotion using only durable action/proof objects. */
export function recoverCutRepairPromotionSync(
  producerDir: string,
  idempotencyKey: string,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionOutcome {
  const record = recordById(producerDir, idempotencyKey);
  assertRecoveryHead(producerDir, record, [
    record.expectedParentRevisionHash,
    record.childRevisionHash,
  ]);
  const outcome = recoverCutRepairTransitionSync({
    producerDir,
    transition: "promotion",
    idempotencyKey,
    verify: (record) => verifyPromotionRecord(producerDir, record),
  }, {
    after: (boundary) => {
      if (boundary === "after-advance") {
        assertRecoveryHead(producerDir, record, [record.childRevisionHash]);
        activateCutRepairPromotionMediaSync(producerDir, record);
      }
      hooks.after?.(boundary);
    },
  });
  if (["committed", "replayed"].includes(outcome.status)) {
    assertRecoveryHead(producerDir, record, [record.childRevisionHash]);
    verifyCutRepairPromotionMediaSync(producerDir, record);
  }
  return outcome;
}

/** Create/retry CUT_REVIEW -> PICTURE_LOCKED without rebasing the repair. */
export function promoteCutRepairReviewSync(
  input: CutRepairPromotionTransitionInput,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionOutcome {
  const action = parseCutRepairPromotionActionV1(input.action);
  if (existingRecord(input.producerDir, action)) {
    return recoverCutRepairPromotionSync(
      input.producerDir, action.idempotencyKey, hooks);
  }
  const record = materializeCutRepairPromotionSync(input, hooks);
  return recoverCutRepairPromotionSync(
    input.producerDir, record.idempotencyKey, hooks);
}
