import { createHash } from "node:crypto";
import path from "node:path";
import { atomicWriteFileSync } from "./atomic-file";
import type { ApprovalRecord } from "./auto-edit-approval";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  AUTO_EDIT_PROMOTION_RECONCILIATION_FILE,
  AUTO_EDIT_QC_DIR,
  approvalPath,
  assertPromotionAuthority,
  previewStalePath,
} from "./auto-edit-quality-artifacts";
import {
  removeNodeDurable,
  type PromotionNodeState,
} from "./candidate-promotion-fs";
import {
  recoverCandidatePromotionSync,
  runRecoverablePromotionSync,
  type PromotionRecoveryOutcome,
  type PromotionCrashBoundary,
  type PromotionTopology,
} from "./candidate-promotion-transaction";

export interface CandidatePromotionHooks {
  beforeApproval?: () => void;
  afterApproval?: () => void;
  rollbackAuthority?: () => void;
  approvalWriter?: (dir: string, record: ApprovalRecord) => void;
  authorityMutablePaths?: string[];
  acceptCommitReady?: () => boolean;
  confirmCommitted?: () => void;
  allowMutableRollback?: (
    destination: string,
    current: PromotionNodeState,
    prior: PromotionNodeState,
  ) => boolean;
  afterBoundary?: (boundary: PromotionCrashBoundary) => void;
}

interface CandidatePromotionShape {
  topology: PromotionTopology;
  media: Array<{ source: string; destination: string }>;
  diagnostics: Array<{ source: string; destination: string }>;
}

export function candidatePromotionTransactionId(
  candidate: string,
  producerDir: string,
  record: ApprovalRecord,
): string {
  return canonicalJsonSha256({
    kind: "auto-edit-candidate-promotion-v1",
    candidate: path.resolve(candidate),
    producerDir: path.resolve(producerDir),
    approval: record,
  });
}

function promotionShape(
  candidate: string,
  producerDir: string,
  record: ApprovalRecord,
  mutablePaths: string[],
): CandidatePromotionShape {
  const candidateDir = path.dirname(candidate);
  const media = [
    {
      source: candidate,
      destination: path.join(producerDir, "final.mp4"),
      missingSource: "reject" as const,
    },
    {
      source: `${candidate}.assembled.json`,
      destination: path.join(producerDir, "final.mp4.assembled.json"),
      missingSource: "reject" as const,
    },
    {
      source: candidate.replace(/\.mp4$/, ".proxy.mp4"),
      destination: path.join(producerDir, "final.proxy.mp4"),
      missingSource: "delete-destination" as const,
    },
  ];
  const diagnostics = [
    "audit_report.json", "audit_report.md", "graphics_placements.json",
    "audit_frames",
  ].map((name) => ({
    source: path.join(candidateDir, name),
    destination: path.join(producerDir, name),
    missingSource: "delete-destination" as const,
  }));
  const topology = {
    scopeRoot: producerDir,
    transactionId: candidatePromotionTransactionId(
      candidate, producerDir, record),
    recoveryRoot: path.join(producerDir, AUTO_EDIT_QC_DIR, "promotion-recovery"),
    reconciliationPath: path.join(
      producerDir, AUTO_EDIT_PROMOTION_RECONCILIATION_FILE),
    moves: media,
    copies: diagnostics,
    mutablePaths: [
      approvalPath(producerDir),
      previewStalePath(producerDir),
      ...mutablePaths,
    ],
  };
  return { topology, media, diagnostics };
}

function writeApproval(dir: string, record: ApprovalRecord): void {
  const destination = approvalPath(dir);
  atomicWriteFileSync(
    destination, `${JSON.stringify(record, null, 2)}\n`, { mode: 0o600 });
  removeNodeDurable(previewStalePath(dir));
}

function approvalFileState(record: ApprovalRecord): PromotionNodeState {
  const bytes = Buffer.from(`${JSON.stringify(record, null, 2)}\n`);
  return {
    kind: "file",
    sha256: createHash("sha256").update(bytes).digest("hex"),
    size: bytes.length,
  };
}

function defaultMutableAllowance(
  producerDir: string,
  record: ApprovalRecord,
  hooks: CandidatePromotionHooks,
): CandidatePromotionHooks["allowMutableRollback"] {
  const approval = approvalPath(producerDir);
  const preview = previewStalePath(producerDir);
  const expected = approvalFileState(record);
  return (destination, current, prior) => {
    if (destination === approval) {
      return JSON.stringify(current) === JSON.stringify(expected);
    }
    if (destination === preview) return current.kind === "missing";
    return hooks.allowMutableRollback?.(
      destination, current, prior) === true;
  };
}

function recoveryHooks(
  producerDir: string,
  record: ApprovalRecord,
  hooks: CandidatePromotionHooks,
) {
  return {
    rollbackAuthority: hooks.rollbackAuthority,
    acceptCommitReady: hooks.acceptCommitReady,
    confirmCommitted: hooks.confirmCommitted,
    allowMutableRollback: defaultMutableAllowance(
      producerDir, record, hooks),
  };
}

export function recoverApprovedCandidatePromotionSync(
  candidate: string,
  producerDir: string,
  record: ApprovalRecord,
  hooks: CandidatePromotionHooks = {},
): PromotionRecoveryOutcome {
  const shape = promotionShape(
    candidate, producerDir, record, hooks.authorityMutablePaths ?? []);
  return recoverCandidatePromotionSync(
    shape.topology, recoveryHooks(producerDir, record, hooks));
}

export function promoteApprovedCandidate(
  candidate: string,
  producerDir: string,
  record: ApprovalRecord,
  hooks: CandidatePromotionHooks = {},
): void {
  const recovered = recoverApprovedCandidatePromotionSync(
    candidate, producerDir, record, hooks);
  if (recovered === "recovered-new") return;
  assertPromotionAuthority(candidate, producerDir, record);
  const shape = promotionShape(
    candidate, producerDir, record, hooks.authorityMutablePaths ?? []);
  runRecoverablePromotionSync({
    ...shape.topology,
    commit: () => {
      hooks.beforeApproval?.();
      (hooks.approvalWriter ?? writeApproval)(producerDir, record);
      hooks.afterApproval?.();
    },
    ...recoveryHooks(producerDir, record, hooks),
    afterBoundary: hooks.afterBoundary,
  });
}
