import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import path from "node:path";

export const SURGICAL_RECONCILIATION_FILE =
  ".sniper-surgical-reconciliation.json";
export const SURGICAL_RECONCILIATION_CANDIDATE_FILE =
  ".sniper-surgical-reconciliation-candidate.json";
export const QC_PROMOTION_RECONCILIATION_FILE =
  ".sniper-qc-promotion-reconciliation.json";
const QC_PROMOTION_INTENT_FILE = path.join(
  ".sniper-authority-v1", "intents", "QC_PROMOTION.json");

export class PromotionReconciliationError extends Error {}

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function artifactPath(dir: string, name: string): string {
  return path.join(dir, name);
}

function nodePresent(filePath: string): boolean {
  try {
    lstatSync(filePath);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ENOENT";
  }
}

function assertNoQcPromotionReconciliation(dir: string): void {
  const qcIntentPath = artifactPath(dir, QC_PROMOTION_INTENT_FILE);
  if (nodePresent(qcIntentPath)) {
    throw new PromotionReconciliationError(
      "Auto Edit QC promotion has an unresolved durable intent; "
        + "resume Auto Edit recovery before another project mutation",
    );
  }
  const qcPromotionPath = artifactPath(
    dir, QC_PROMOTION_RECONCILIATION_FILE);
  if (nodePresent(qcPromotionPath)) {
    throw new PromotionReconciliationError(
      "Auto Edit QC promotion has unresolved media/render-graph state; "
        + `reconcile ${qcPromotionPath} before another project mutation`,
    );
  }
}

/** No project writer may run across unresolved Ask Editor promotion state. */
export function assertNoPromotionReconciliation(dir: string): void {
  assertNoQcPromotionReconciliation(dir);
  const evidencePath = artifactPath(dir, SURGICAL_RECONCILIATION_FILE);
  const candidatePath = artifactPath(
    dir, SURGICAL_RECONCILIATION_CANDIDATE_FILE,
  );
  const evidenceExists = nodePresent(evidencePath);
  const candidateExists = nodePresent(candidatePath);
  if (!evidenceExists && !candidateExists) return;
  if (!evidenceExists || !candidateExists) {
    throw new PromotionReconciliationError(
      "Ask Editor promotion reconciliation evidence is incomplete; "
        + "resolve it before another project mutation",
    );
  }
  try {
    const evidence = JSON.parse(readFileSync(evidencePath, "utf8")) as
      Record<string, unknown>;
    const stat = lstatSync(candidatePath);
    const candidate = readFileSync(candidatePath);
    const valid = evidence && typeof evidence === "object"
      && !Array.isArray(evidence)
      && evidence.schemaVersion === 1
      && evidence.status === "manual-reconciliation-required"
      && evidence.promotedChildHash === sha256(candidate)
      && evidence.retainedCandidatePath === candidatePath
      && stat.isFile() && !stat.isSymbolicLink() && stat.nlink === 1;
    if (!valid) throw new Error("malformed reconciliation evidence");
  } catch {
    throw new PromotionReconciliationError(
      "Ask Editor promotion reconciliation evidence is unreadable or malformed; "
        + "resolve it before another project mutation",
    );
  }
  throw new PromotionReconciliationError(
    "Ask Editor has an unresolved post-promotion conflict; "
      + `reconcile ${evidencePath} before another project mutation`,
  );
}
