import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { parseApprovalRecord, type ApprovalRecord } from
  "./auto-edit-approval";
import {
  approvalPath,
  previewStalePath,
} from "./auto-edit-quality-artifacts";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import {
  assertNoPromotionReconciliation,
  QC_PROMOTION_RECONCILIATION_FILE,
} from "./ask-editor-reconciliation";
import {
  producerAuthorityPaths,
  readApprovedHeadSync,
  readAuthorityJsonSync,
  writeMutableAuthorityJsonSync,
} from "./producer-authority-files";
import type { CurrentRenderGraphAuthority } from
  "./current-render-graph-authority";
import {
  parseProducerQcPromotionIntentV1,
  type ProducerQcPromotionIntentV1,
  type QcPromotionOldStateV1,
} from "./producer-qc-promotion-intent-model";
import { resolveProducerAuthorityHeadSync } from
  "./producer-revision-head";
import { qcPromotionExactChildSelectedSync } from
  "./producer-qc-promotion-exact-child";

export interface QcPromotionIntentExpectation {
  graphHash: string;
  approval: ApprovalRecord;
}

export interface PreparedQcPromotionIntent {
  intentId: string;
}

export type QcPromotionRecovery =
  "none" | "recovered-old" | "recovered-exact-child";

export class ProducerQcPromotionReconciliationError extends Error {}

function uncheckedIntentPath(producerDir: string): string {
  return path.join(
    path.resolve(producerDir),
    ".sniper-authority-v1",
    "intents",
    "QC_PROMOTION.json",
  );
}

export function qcPromotionIntentPath(producerDir: string): string {
  return path.join(
    producerAuthorityPaths(producerDir).intents,
    "QC_PROMOTION.json",
  );
}

function optionalFileHash(filePath: string): string | null {
  return fileSha256(filePath) ?? null;
}

function liveState(producerDir: string): QcPromotionOldStateV1 {
  return {
    finalMediaFileHash: optionalFileHash(
      path.join(producerDir, "final.mp4")),
    finalProofFileHash: optionalFileHash(
      path.join(producerDir, "final.mp4.assembled.json")),
    approvalFileHash: optionalFileHash(approvalPath(producerDir)),
    previewMarkerFileHash: optionalFileHash(previewStalePath(producerDir)),
    activeGraphPointerFileHash: optionalFileHash(path.join(
      producerDir, ".render-graph-v1", "ACTIVE.json")),
  };
}

function sameState(
  left: QcPromotionOldStateV1,
  right: QcPromotionOldStateV1,
): boolean {
  return canonicalJsonSha256(left) === canonicalJsonSha256(right);
}

function intentIdentity(value: Omit<
  ProducerQcPromotionIntentV1,
  "intentId" | "phase" | "childRevisionHash"
  | "graphReceiptHash" | "graphPointerHash"
>): string {
  return canonicalJsonSha256(value);
}

function preparedValue(
  producerDir: string,
  parentRevisionHash: string,
  expectedApprovedHead: string | null,
  expected: QcPromotionIntentExpectation,
): ProducerQcPromotionIntentV1 {
  const approval = parseApprovalRecord(expected.approval);
  if (!approval) throw new Error("QC promotion approval is malformed");
  const stable = {
    schemaVersion: 1 as const,
    kind: "producer-qc-promotion" as const,
    parentRevisionHash,
    expectedApprovedHead,
    intendedGraphHash: expected.graphHash,
    intendedApprovalHash: canonicalJsonSha256(approval),
    intendedFinalHash: approval.finalHash,
    intendedPlanHash: approval.planHash,
    intendedManifestHash: approval.manifestHash,
    oldState: liveState(producerDir),
  };
  return parseProducerQcPromotionIntentV1({
    ...stable,
    intentId: intentIdentity(stable),
    phase: "prepared",
    childRevisionHash: null,
    graphReceiptHash: null,
    graphPointerHash: null,
  });
}

export function readProducerQcPromotionIntentSync(
  producerDir: string,
): ProducerQcPromotionIntentV1 | null {
  const unchecked = uncheckedIntentPath(producerDir);
  if (!existsSync(unchecked)) return null;
  const destination = qcPromotionIntentPath(producerDir);
  return parseProducerQcPromotionIntentV1(
    readAuthorityJsonSync(destination));
}

export function prepareProducerQcPromotionIntentSync(
  producerDir: string,
  parentRevisionHash: string,
  expectedApprovedHead: string | null,
  expected: QcPromotionIntentExpectation,
): PreparedQcPromotionIntent {
  recoverProducerQcPromotionIntentSync(producerDir);
  assertNoPromotionReconciliation(producerDir);
  const intent = preparedValue(
    producerDir, parentRevisionHash, expectedApprovedHead, expected);
  writeMutableAuthorityJsonSync(qcPromotionIntentPath(producerDir), intent);
  return { intentId: intent.intentId };
}

function requireIntent(
  producerDir: string,
  expectedIntentId: string,
): ProducerQcPromotionIntentV1 {
  const intent = readProducerQcPromotionIntentSync(producerDir);
  if (!intent || intent.intentId !== expectedIntentId) {
    throw new Error("QC promotion durable intent changed or disappeared");
  }
  return intent;
}

export function bindProducerQcPromotionChildSync(
  producerDir: string,
  expectedIntentId: string,
  childRevisionHash: string,
  graph: CurrentRenderGraphAuthority,
): void {
  const intent = requireIntent(producerDir, expectedIntentId);
  const next = parseProducerQcPromotionIntentV1({
    ...intent,
    phase: "child-materialized",
    childRevisionHash,
    graphReceiptHash: graph.receiptHash,
    graphPointerHash: graph.activePointerHash,
  });
  writeMutableAuthorityJsonSync(qcPromotionIntentPath(producerDir), next);
}

function oldStateSelected(
  producerDir: string,
  intent: ProducerQcPromotionIntentV1,
): boolean {
  try {
    const paths = producerAuthorityPaths(producerDir);
    return resolveProducerAuthorityHeadSync(producerDir)
        === intent.parentRevisionHash
      && readApprovedHeadSync(paths) === intent.expectedApprovedHead
      && sameState(liveState(producerDir), intent.oldState);
  } catch {
    return false;
  }
}

function reconciliation(
  producerDir: string,
  intent: ProducerQcPromotionIntentV1,
): never {
  const destination = path.join(
    producerDir, QC_PROMOTION_RECONCILIATION_FILE);
  writeMutableAuthorityJsonSync(destination, {
    schemaVersion: 1,
    status: "reconciliation-required",
    reason: "durable QC promotion is neither exact old state nor exact child",
    intentId: intent.intentId,
    intentPhase: intent.phase,
    parentRevisionHash: intent.parentRevisionHash,
    childRevisionHash: intent.childRevisionHash,
    observedLiveState: liveState(producerDir),
  });
  throw new ProducerQcPromotionReconciliationError(
    `QC promotion ${intent.intentId} requires reconciliation`);
}

/** Resolve a crash only when state is provably old or the exact QC child. */
export function recoverProducerQcPromotionIntentSync(
  producerDir: string,
): QcPromotionRecovery {
  const intent = readProducerQcPromotionIntentSync(producerDir);
  if (!intent) return "none";
  if (oldStateSelected(producerDir, intent)) {
    rmSync(qcPromotionIntentPath(producerDir));
    return "recovered-old";
  }
  if (qcPromotionExactChildSelectedSync(producerDir, intent)) {
    rmSync(qcPromotionIntentPath(producerDir));
    return "recovered-exact-child";
  }
  return reconciliation(producerDir, intent);
}
