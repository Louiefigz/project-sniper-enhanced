import {
  existsSync,
  lstatSync,
  mkdirSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import {
  parseCutRepairMediaActivationV1,
  type CutRepairMediaActivationV1,
} from "@/lib/producer/contracts/cut-repair-media-activation";
import { parseCutRepairRenderedCandidateV1 } from
  "@/lib/producer/contracts/cut-repair-rendered-candidate";
import {
  activateExactRenderGraphCandidateSync,
  rollbackExactRenderGraphCandidateSync,
  verifyExactRenderGraphCandidateSync,
  type ExactRenderGraphActivationInput,
} from "./current-render-graph-candidate";
import {
  observeCurrentRenderGraphAuthoritySync,
} from "./current-render-graph-authority";
import { atomicWriteFileSync } from "./atomic-file";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from
  "./auto-edit-hash";
import { runRecoverablePromotionSync } from
  "./candidate-promotion-transaction";
import type { PromotionCrashBoundary } from
  "./candidate-promotion-transaction";
import { preparedStagingPath, restorePreparedMediaSync } from
  "./cut-repair-preparation-media";
import type { CutRepairTransitionRecord } from
  "./cut-repair-transition-model";
import {
  assertObjectHashSync,
  authorityKey,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
} from "./producer-authority-files";

function v2Candidate(
  producerDir: string,
  record: CutRepairTransitionRecord,
): Record<string, unknown> | null {
  const paths = producerAuthorityPaths(producerDir);
  const candidate = assertObjectHashSync(
    paths.objects.cutRepairs, record.artifactHashes.cutRepairCandidate);
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
    throw new Error("stored cut repair candidate is malformed");
  }
  const row = candidate as Record<string, unknown>;
  return row.schemaVersion === 2 ? row : null;
}

function activationRecordPath(
  producerDir: string,
  record: CutRepairTransitionRecord,
): string {
  const paths = producerAuthorityPaths(producerDir);
  const root = path.join(paths.sagas, "cut-repair-media-activation");
  const records = path.join(root, "records");
  ensureRealDirectory(root);
  ensureRealDirectory(records);
  return path.join(records, `${authorityKey(record.idempotencyKey)}.json`);
}

function createDirectory(directory: string): void {
  try {
    mkdirSync(directory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
}

function ensureRealDirectory(directory: string): void {
  if (!existsSync(directory)) createDirectory(directory);
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || realpathSync(directory) !== directory) {
    throw new Error("cut repair activation authority directory must be real");
  }
}

function publishPlan(
  producerDir: string,
  planObjectHash: string,
): void {
  const paths = producerAuthorityPaths(producerDir);
  const plan = assertObjectHashSync(paths.objects.plans, planObjectHash);
  const bytes = canonicalJson(plan);
  const destination = path.join(producerDir, "edit_plan.json");
  if (fileSha256(destination) !== planObjectHash) {
    atomicWriteFileSync(destination, bytes);
  }
  if (fileSha256(destination) !== planObjectHash) {
    throw new Error("cut repair activated plan did not publish exactly");
  }
}

function publishReceipt(
  producerDir: string,
  record: CutRepairTransitionRecord,
  renderedHash: string,
  authority: ReturnType<typeof activateExactRenderGraphCandidateSync>,
): CutRepairMediaActivationV1 {
  const receipt = parseCutRepairMediaActivationV1({
    schemaVersion: 1,
    kind: "cut-repair-media-activation",
    promotionActionHash: record.actionHash,
    promotedRevisionHash: record.childRevisionHash,
    renderedCandidateHash: renderedHash,
    candidateSha256: authority.finalMediaHash,
    graphHash: authority.graphHash,
    graphReceiptHash: authority.receiptHash,
    activePointerHash: authority.activePointerHash,
  });
  const paths = producerAuthorityPaths(producerDir);
  writeAuthorityObjectSync(paths.objects.receipts, receipt);
  publishImmutableAuthorityJsonSync(
    activationRecordPath(producerDir, record), receipt);
  return receipt;
}

function reopenReceipt(
  producerDir: string,
  record: CutRepairTransitionRecord,
  renderedHash: string,
  graph: ExactRenderGraphActivationInput,
): CutRepairMediaActivationV1 {
  const filePath = activationRecordPath(producerDir, record);
  if (!existsSync(filePath)) {
    throw new Error("cut repair activation receipt is missing");
  }
  const receipt = parseCutRepairMediaActivationV1(
    readAuthorityJsonSync(filePath));
  const authority = observeCurrentRenderGraphAuthoritySync({
    producerDir,
    expectedGraphHash: graph.graphHash,
    expectedFinalHash: graph.candidateSha256,
  });
  if (receipt.promotionActionHash !== record.actionHash
      || receipt.renderedCandidateHash !== renderedHash
      || receipt.candidateSha256 !== graph.candidateSha256
      || receipt.graphHash !== graph.graphHash
      || receipt.graphReceiptHash !== authority.receiptHash
      || receipt.activePointerHash !== authority.activePointerHash) {
    throw new Error("cut repair activation receipt changed binding");
  }
  return receipt;
}

interface CutRepairActivationContext {
  producerDir: string;
  record: CutRepairTransitionRecord;
  renderedHash: string;
  graph: ExactRenderGraphActivationInput;
  planHash: string;
  root: string;
  transactionId: string;
}

function activationContext(
  producerDir: string,
  record: CutRepairTransitionRecord,
  candidate: Record<string, unknown>,
): CutRepairActivationContext {
  const rendered = parseCutRepairRenderedCandidateV1(
    candidate.renderedCandidate);
  const candidatePath = preparedStagingPath(
    producerDir, rendered.candidatePath, "cut repair activation candidate");
  restorePreparedMediaSync({
    producerDir,
    path: candidatePath,
    hash: rendered.candidateSha256,
    extension: ".mp4",
  });
  const renderedHash = canonicalJsonSha256(rendered);
  return {
    producerDir,
    record,
    renderedHash,
    graph: {
      candidatePath,
      producerDir,
      candidateSha256: rendered.candidateSha256,
      graphHash: rendered.reviewRenderGraphHash,
    },
    planHash: rendered.reviewPlanObjectHash,
    root: path.join(
      producerAuthorityPaths(producerDir).sagas,
      "cut-repair-media-activation",
    ),
    transactionId: canonicalJsonSha256({
      kind: "cut-repair-media-activation-v1",
      actionHash: record.actionHash,
      renderedCandidateHash: renderedHash,
    }),
  };
}

function runActivation(
  context: CutRepairActivationContext,
  afterBoundary?: (boundary: PromotionCrashBoundary) => void,
): CutRepairMediaActivationV1 {
  const {
    producerDir, record, renderedHash, graph, planHash, root, transactionId,
  } = context;
  const finalPath = path.join(producerDir, "final.mp4");
  let receipt: CutRepairMediaActivationV1 | null = null;
  const confirmCommitted = () => {
    receipt = reopenReceipt(
      producerDir, record, renderedHash, graph);
  };
  verifyExactRenderGraphCandidateSync(graph);
  runRecoverablePromotionSync({
    scopeRoot: producerDir,
    transactionId,
    recoveryRoot: path.join(root, "recovery"),
    reconciliationPath: path.join(root, "RECONCILIATION.json"),
    moves: [],
    copies: [{
      source: graph.candidatePath,
      destination: finalPath,
      missingSource: "reject",
    }],
    mutablePaths: [path.join(producerDir, "edit_plan.json")],
    commit: () => {
      publishPlan(producerDir, planHash);
      const authority = activateExactRenderGraphCandidateSync(graph);
      receipt = publishReceipt(
        producerDir, record, renderedHash, authority);
    },
    rollbackAuthority: () => rollbackExactRenderGraphCandidateSync(graph),
    acceptCommitReady: () => {
      try {
        confirmCommitted();
        return true;
      } catch {
        return false;
      }
    },
    confirmCommitted,
    allowMutableRollback: (destination, current) =>
      destination === path.join(producerDir, "edit_plan.json")
      && current.kind === "file"
      && current.sha256 === planHash,
    afterBoundary,
  });
  return receipt ?? reopenReceipt(producerDir, record, renderedHash, graph);
}

function activate(
  producerDir: string,
  record: CutRepairTransitionRecord,
  candidate: Record<string, unknown>,
  afterBoundary?: (boundary: PromotionCrashBoundary) => void,
): CutRepairMediaActivationV1 {
  return runActivation(
    activationContext(producerDir, record, candidate), afterBoundary);
}

/** Activate exact V2 media idempotently; legacy V1 records remain read-only. */
export function activateCutRepairPromotionMediaSync(
  producerDir: string,
  record: CutRepairTransitionRecord,
  afterBoundary?: (boundary: PromotionCrashBoundary) => void,
): void {
  const candidate = v2Candidate(producerDir, record);
  if (candidate) activate(producerDir, record, candidate, afterBoundary);
}

/** Reopen the immutable activation record and current selected bytes. */
export function verifyCutRepairPromotionMediaSync(
  producerDir: string,
  record: CutRepairTransitionRecord,
): void {
  const candidate = v2Candidate(producerDir, record);
  if (!candidate) return;
  const expected = activate(producerDir, record, candidate);
  const rendered = parseCutRepairRenderedCandidateV1(
    candidate.renderedCandidate);
  const filePath = activationRecordPath(producerDir, record);
  if (!existsSync(filePath)) {
    throw new Error("cut repair V2 promotion has no media activation receipt");
  }
  const receipt = parseCutRepairMediaActivationV1(
    readAuthorityJsonSync(filePath));
  if (receipt.renderedCandidateHash !== canonicalJsonSha256(rendered)
      || receipt.candidateSha256 !== rendered.candidateSha256
      || receipt.graphHash !== rendered.reviewRenderGraphHash) {
    throw new Error("cut repair media activation receipt changed binding");
  }
  if (canonicalJsonSha256(receipt) !== canonicalJsonSha256(expected)) {
    throw new Error("cut repair media activation receipt changed identity");
  }
}
