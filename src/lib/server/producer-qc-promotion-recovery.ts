import {
  producerAuthorityPaths,
  readApprovedHeadSync,
  writeApprovedHeadSync,
} from "./producer-authority-files";
import {
  readProducerQcPromotionIntentSync,
  recoverProducerQcPromotionIntentSync,
} from "./producer-qc-promotion-intent";
import {
  qcPromotionExactChildSelectedSync,
} from "./producer-qc-promotion-exact-child";
import { resolveProducerAuthorityHeadSync } from
  "./producer-revision-head";
import { removeNodeDurable } from "./candidate-promotion-fs";

export type QcPromotionCrashDisposition =
  "none" | "rollback-allowed" | "exact-child" | "blocked";

/** Classify without mutating the durable QC intent or either revision head. */
export function classifyQcPromotionCrashSync(
  producerDir: string,
): QcPromotionCrashDisposition {
  const intent = readProducerQcPromotionIntentSync(producerDir);
  if (!intent) return "none";
  if (qcPromotionExactChildSelectedSync(producerDir, intent)) {
    return "exact-child";
  }
  try {
    const paths = producerAuthorityPaths(producerDir);
    const active = resolveProducerAuthorityHeadSync(producerDir);
    const approved = readApprovedHeadSync(paths);
    const allowedApproved = approved === intent.expectedApprovedHead
      || (intent.childRevisionHash !== null
        && approved === intent.childRevisionHash);
    return active === intent.parentRevisionHash && allowedApproved
      ? "rollback-allowed" : "blocked";
  } catch {
    return "blocked";
  }
}

function restoreApprovedHead(producerDir: string): void {
  const intent = readProducerQcPromotionIntentSync(producerDir);
  if (!intent) return;
  const paths = producerAuthorityPaths(producerDir);
  const approved = readApprovedHeadSync(paths);
  if (approved === intent.expectedApprovedHead) return;
  if (!intent.childRevisionHash || approved !== intent.childRevisionHash) {
    throw new Error("QC approved head is foreign during crash recovery");
  }
  if (intent.expectedApprovedHead) {
    writeApprovedHeadSync(paths, intent.expectedApprovedHead);
  } else {
    removeNodeDurable(paths.approvedHead);
  }
}

/** Complete only the exact child and remove its intent after full readback. */
export function settleExactQcPromotionChildSync(
  producerDir: string,
): void {
  const disposition = classifyQcPromotionCrashSync(producerDir);
  if (disposition === "none") return;
  if (disposition !== "exact-child") {
    throw new Error("QC promotion did not select its exact intended child");
  }
  const recovered = recoverProducerQcPromotionIntentSync(producerDir);
  if (recovered !== "recovered-exact-child") {
    throw new Error("QC exact child recovery did not settle its intent");
  }
}

/**
 * Restore the mutable approved head only after media and ACTIVE graph have
 * reopened the exact old generation.
 */
export function settleOldQcPromotionSync(producerDir: string): void {
  if (classifyQcPromotionCrashSync(producerDir) !== "rollback-allowed") {
    throw new Error("QC promotion crash is not safe to roll back");
  }
  restoreApprovedHead(producerDir);
  const recovered = recoverProducerQcPromotionIntentSync(producerDir);
  if (recovered !== "recovered-old") {
    throw new Error("QC old generation recovery did not settle its intent");
  }
  if (readProducerQcPromotionIntentSync(producerDir)) {
    throw new Error("QC old generation intent remained after recovery");
  }
}
