import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { parseCommitIntentV1 } from
  "@/lib/producer/contracts/commit-intent";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  authorityKey,
  assertObjectHashSync,
  producerAuthorityPaths,
  readAuthorityJsonSync,
} from "./producer-authority-files";
import {
  parseCutRepairTransitionRecord,
  type CutRepairTransitionKind,
} from "./cut-repair-transition-model";
import { resolveProducerAuthorityHeadSync } from "./producer-revision-head";

export class CutRepairTransitionPendingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CutRepairTransitionPendingError";
  }
}

function pendingIntents(producerDir: string): string[] {
  const authority = path.join(producerDir, ".sniper-authority-v1");
  if (!existsSync(authority)) return [];
  const sagaRoot = path.join(authority, "sagas");
  return ["ripple-reopen", "review", "promotion"].flatMap((phase) => {
    const directory = path.join(
      sagaRoot, `cut-repair-${phase}`, "intents");
    if (!existsSync(directory)) return [];
    return readdirSync(directory)
      .filter((name) => name.endsWith(".json"))
      .map((name) => parseCommitIntentV1(
        readAuthorityJsonSync(path.join(directory, name))))
      .filter((intent) => !["COMMITTED", "ABORTED"].includes(intent.state))
      .map((intent) => `${phase}:${intent.idempotencyKey}:${intent.state}`);
  }).sort();
}

interface CutRepairRecoveryScope {
  producerDir: string;
  reviewIdempotencyKey: string;
  promotionIdempotencyKey: string;
  expectedReviewRevisionHash: string;
}

/** Admit only recovery for this exact ripple-reopen request identity. */
export function assertCutRepairRippleRecoverySync(
  producerDir: string,
  idempotencyKey: string,
): void {
  for (const pending of pendingIntents(producerDir)) {
    if (!pending.startsWith(`ripple-reopen:${idempotencyKey}:`)) {
      throw new CutRepairTransitionPendingError(
        `cut repair transition ${pending} belongs to another reopen request`);
    }
  }
}

/** Resolve an existing immutable phase record without creating recovery state. */
export function cutRepairTransitionChildSync(
  producerDir: string,
  transition: CutRepairTransitionKind,
  idempotencyKey: string,
): string | null {
  const paths = producerAuthorityPaths(producerDir);
  const filePath = path.join(
    paths.sagas, `cut-repair-${transition}`, "records",
    `${authorityKey(idempotencyKey)}.json`);
  if (!existsSync(filePath)) return null;
  const record = parseCutRepairTransitionRecord(
    readAuthorityJsonSync(filePath));
  if (record.transition !== transition
      || record.idempotencyKey !== idempotencyKey) {
    throw new CutRepairTransitionPendingError(
      "cut repair transition record is bound to another recovery action");
  }
  return record.childRevisionHash;
}

/** Admit recovery only for the exact package that owns pending phase state. */
export function assertCutRepairRecoveryPackageSync(
  input: CutRepairRecoveryScope,
): void {
  for (const pending of pendingIntents(input.producerDir)) {
    const expected = pending.startsWith("review:")
      ? `review:${input.reviewIdempotencyKey}:`
      : `promotion:${input.promotionIdempotencyKey}:`;
    if (!pending.startsWith(expected)) {
      throw new CutRepairTransitionPendingError(
        `cut repair transition ${pending} belongs to another package`);
    }
  }
  const authority = path.join(
    input.producerDir, ".sniper-authority-v1", "advances", "GENESIS.json");
  if (!existsSync(authority)) return;
  const head = resolveProducerAuthorityHeadSync(input.producerDir);
  const paths = producerAuthorityPaths(input.producerDir);
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, head));
  if (revision.workflowState === "CUT_REVIEW"
      && head !== input.expectedReviewRevisionHash) {
    throw new CutRepairTransitionPendingError(
      "selected CUT_REVIEW belongs to another recovery package");
  }
}

/** Admit review replay only for that review key, never a pending promotion. */
export function assertCutRepairReviewRecoverySync(
  producerDir: string,
  reviewIdempotencyKey: string,
): void {
  for (const pending of pendingIntents(producerDir)) {
    if (!pending.startsWith(`review:${reviewIdempotencyKey}:`)) {
      throw new CutRepairTransitionPendingError(
        `cut repair transition ${pending} belongs to another review`);
    }
  }
}

/** Approval may read only an already-selected, fully settled review child. */
export function assertCutRepairApprovalAdmissionSync(
  producerDir: string,
  reviewIdempotencyKey: string,
): void {
  const pending = pendingIntents(producerDir)[0];
  if (pending) {
    throw new CutRepairTransitionPendingError(
      `CUT_REVIEW_NOT_STAGED: transition ${pending} is not settled`);
  }
  const child = cutRepairTransitionChildSync(
    producerDir, "review", reviewIdempotencyKey);
  if (!child || resolveProducerAuthorityHeadSync(producerDir) !== child) {
    throw new CutRepairTransitionPendingError(
      "CUT_REVIEW_NOT_STAGED: approve cannot create or recover its review");
  }
}

/** Block every other writer while a repair transition needs resume/review. */
export function assertNoPendingCutRepairTransitionSync(
  producerDir: string,
): void {
  const pending = pendingIntents(producerDir)[0];
  if (pending) {
    throw new CutRepairTransitionPendingError(
      `cut repair transition ${pending} requires exact-package recovery`);
  }
  const authority = path.join(producerDir, ".sniper-authority-v1");
  if (!existsSync(path.join(authority, "advances", "GENESIS.json"))) return;
  const paths = producerAuthorityPaths(producerDir);
  const head = resolveProducerAuthorityHeadSync(producerDir);
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, head));
  if (revision.workflowState === "CUT_REVIEW"
      && revision.authoritativeSidecars.cutRepairReviewAction) {
    throw new CutRepairTransitionPendingError(
      "cut repair CUT_REVIEW head requires its exact promotion package");
  }
}
