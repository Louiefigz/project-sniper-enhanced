import { randomUUID } from "node:crypto";
import path from "node:path";
import {
  sameAutoEditAuthority,
  type AutoEditAuthoritySnapshot,
} from "@/lib/server/auto-edit-authority-snapshot";
import type { ProducerReviewResult } from "./brain-review-runner";
import {
  REQUIRED_CLEAN_CUT_REVIEWS,
  type CleanCutReviewArtifact,
  type StoredCutReviewArtifact,
} from "./cut-review-approval";
import type { CutApprovalReceipt } from "./cut-approval";
import {
  bindCutReviewPacket,
  buildCutReviewPacket,
  CUT_REVIEW_PACKET_NAME,
  type CutReviewPacketRef,
} from "./cut-review-packet";
import type { ProducerReview } from "./review-contract";
import { rejectedBatchResult } from "./review-batch";
import { AutoEditError } from "./stream";
import type {
  CutReviewLoopDependencies,
  CutReviewLoopRuntime,
} from "./cut-review-loop";

export const MAX_CUT_REVIEW_ROUNDS = 6;

export interface CutRoundResult {
  gate: CutApprovalReceipt;
  review: ProducerReview;
  artifact: CleanCutReviewArtifact;
  authority: AutoEditAuthoritySnapshot;
}

interface CutBatchContext {
  run: CutReviewLoopRuntime;
  gate: CutApprovalReceipt;
  authority: AutoEditAuthoritySnapshot;
  deps: CutReviewLoopDependencies;
}

interface CutPacketEntry {
  round: number;
  packet: CutReviewPacketRef;
}

function safeToken(run: CutReviewLoopRuntime): string {
  const { job } = run;
  return (job.artifactToken ?? job.token).replace(/[^a-zA-Z0-9._-]/g, "_").slice(-96);
}

export function cutRoundDir(run: CutReviewLoopRuntime, round: number): string {
  return path.join(run.job.ctx.dir, ".sniper-qc", safeToken(run), "cut", `round-${round}`);
}

function packetPath(run: CutReviewLoopRuntime, round: number): string {
  return path.join(
    cutRoundDir(run, round), `critic-input-${randomUUID()}`, CUT_REVIEW_PACKET_NAME,
  );
}

function requiredHash(value: string | undefined, label: string): string {
  if (!value) throw new AutoEditError(`missing ${label}`);
  return value;
}

function persistPacket(
  context: CutBatchContext,
  round: number,
): CutReviewPacketRef {
  const { run, gate, authority, deps } = context;
  const packet = buildCutReviewPacket(run.job.ctx, round, gate, authority);
  return bindCutReviewPacket(deps.writeJson(packetPath(run, round), packet), packet);
}

function persistReview(
  context: CutBatchContext,
  entry: CutPacketEntry,
  result: ProducerReviewResult,
): CutRoundResult {
  const { run, gate, authority, deps } = context;
  const { round, packet } = entry;
  const artifact: StoredCutReviewArtifact & {
    inputPacket: CutReviewPacketRef; provider: ProducerReviewResult["provider"]; ms: number;
  } = {
    schemaVersion: 1, stage: "cut", round,
    inputAuthority: authority, inputPacket: packet,
    provider: result.provider, ms: result.ms, review: result.review,
  };
  const artifactPath = deps.writeJson(path.join(cutRoundDir(run, round), "cut-review.json"), artifact);
  const ref = {
    round, path: artifactPath, hash: requiredHash(deps.hash(artifactPath), "cut review hash"),
  };
  return { gate, review: result.review, artifact: ref, authority };
}

function persistCompleted(
  context: CutBatchContext,
  entries: CutPacketEntry[],
  settled: PromiseSettledResult<ProducerReviewResult>[],
): CutRoundResult[] {
  return settled.flatMap((value, index) => {
    if (value.status === "rejected") return [];
    const entry = entries[index];
    const result = persistReview(context, entry, value.value);
    context.run.io.send({
      event: "cut_review_completed", round: entry.round,
      verdict: value.value.review.verdict,
      materialIssues: value.value.review.materialIssues.length,
      provider: value.value.provider, ms: value.value.ms,
      maxRounds: MAX_CUT_REVIEW_ROUNDS,
      requiredCleanReviews: REQUIRED_CLEAN_CUT_REVIEWS,
    });
    return [result];
  });
}

/** Run independent critics concurrently against packets bound to one gate authority. */
export async function runCutReviewBatch(
  run: CutReviewLoopRuntime,
  firstRound: number,
  count: number,
  deps: CutReviewLoopDependencies,
): Promise<CutRoundResult[]> {
  const authority = deps.authority(run.job.ctx);
  const gate = await deps.gate(run.job.ctx, run.io.send);
  if (!sameAutoEditAuthority(authority, deps.authority(run.job.ctx))) {
    throw new AutoEditError("cut authority changed while deterministic validation was running");
  }
  const context = { run, gate, authority, deps };
  const entries = Array.from({ length: count }, (_, index) => {
    const round = firstRound + index;
    const packet = persistPacket(context, round);
    run.io.send({
      event: "cut_review_started", round,
      maxRounds: MAX_CUT_REVIEW_ROUNDS,
      requiredCleanReviews: REQUIRED_CLEAN_CUT_REVIEWS,
    });
    return { round, packet };
  });
  const settled = await Promise.allSettled(entries.map(({ round, packet }) =>
    deps.review({ stage: "cut", ctx: run.job.ctx, round, packet })));
  if (!sameAutoEditAuthority(authority, deps.authority(run.job.ctx))) {
    throw new AutoEditError("cut authority changed while independent critics were running");
  }
  const completed = persistCompleted(context, entries, settled);
  const failure = rejectedBatchResult(settled);
  if (failure) throw failure.reason;
  return completed;
}
