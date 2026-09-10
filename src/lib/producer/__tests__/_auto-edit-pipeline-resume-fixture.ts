import assert from "node:assert/strict";
import {
  mkdirSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import type { AutoEditCtx } from
  "../../../app/api/producer/auto-edit/stream";
import type { PlanningLoopRuntime } from
  "../../../app/api/producer/auto-edit/planning-loop";
import type {
  PipelineDependencies,
  PipelineRuntime,
} from "../../../app/api/producer/auto-edit/pipeline";
import {
  diskCheckpointWriter,
  diskInvalidationWriter,
} from "../../../app/api/producer/auto-edit/pipeline-writers";
import {
  advanceAutoEditJob,
  autoEditJobPath,
  fileSha256,
  readAutoEditJob,
  startAutoEditJob,
  type AutoEditJob,
  type CheckpointUpdate,
} from "../../server/auto-edit-job-store";
import { planContentHash } from "../../server/auto-edit-authority";
import { autoEditAuthoritySnapshot } from
  "../../server/auto-edit-authority-snapshot";
import { promoteApprovedCandidate } from
  "../../server/auto-edit-quality-artifacts";
import { writeApprovalFixture } from "./auto-edit-approval-fixture";

export interface Counts {
  author: number;
  planning: number;
  assemble: number;
  quality: number;
}

export function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(
    planPath,
    '{"planVersion":1,"target":{"mode":"short","scope":"light",'
      + '"lanes":{}},"cutTrack":[]}',
  );
  writeFileSync(manifestPath, '{"sources":[]}');
  writeFileSync(path.join(dir, ".sniper-cut-approval.json"), "{}");
  return {
    dir, scope: "light", planPath, manifestPath, transcriptsDir: source,
    intent: { mode: "short", lanes: {} },
  };
}

let proofClock = Date.now() + 5_000;

export function writeAuthority(
  output: string,
  planPath: string,
  content: string,
): string {
  writeFileSync(output, content);
  const authorityHash = fileSha256(output)!;
  writeFileSync(`${output}.assembled.json`, JSON.stringify({
    planHash: planContentHash(planPath), authorityHash,
  }));
  proofClock += 5_000;
  const future = new Date(proofClock);
  utimesSync(`${output}.assembled.json`, future, future);
  return authorityHash;
}

export function runtime(
  job: AutoEditJob,
  events: Record<string, unknown>[],
): PipelineRuntime {
  const jobPath = autoEditJobPath(job.ctx.dir);
  return {
    job,
    io: {
      send: (event) => events.push(event),
      sendRaw: (line) => events.push({ raw: line }),
      advance: diskCheckpointWriter(jobPath, job.token),
      invalidate: diskInvalidationWriter(jobPath, job.token),
    },
  };
}

function reviewed(run: PlanningLoopRuntime, counts: Counts) {
  counts.planning += 1;
  const planHash = fileSha256(run.job.ctx.planPath)!;
  const manifestHash = fileSha256(run.job.ctx.manifestPath)!;
  const authority = autoEditAuthoritySnapshot(run.job.ctx);
  if (run.job.reviewedPlanHash === planHash
      && run.job.manifestHash === manifestHash
      && run.job.reviewedAuthorityDigest === authority.digest) {
    return Promise.resolve({
      rounds: 2, reviewPaths: [], reviewedPlanHash: planHash,
    });
  }
  run.job = run.io.advance({
    checkpoint: "plan_reviewed", phase: "validating", message: "reviewed",
    planHash, reviewedPlanHash: planHash, manifestHash,
    authorityDigest: authority.digest,
    reviewedAuthorityDigest: authority.digest,
    planningRound: 2, planningRoundsRequired: 2,
  });
  return Promise.resolve({
    rounds: 2, reviewPaths: [], reviewedPlanHash: planHash,
  });
}

export function dependencies(
  counts: Counts,
): Partial<PipelineDependencies> {
  return {
    author: async (ctx, _send, stage) => {
      if (stage === "visual") counts.author += 1;
      writeFileSync(
        ctx.planPath,
        '{"planVersion":1,"target":{"mode":"short","scope":"light",'
          + '"lanes":{}},"cutTrack":[],"authored":true}',
      );
      return {
        code: 0, timedOut: false, errTail: "", ms: 1, provider: "codex",
        authored: { segments: 1, graphics: 0 },
      };
    },
    approveCut: async () => ({} as never),
    reviewCut: async () => ({} as never),
    verifyReviewCut: () => ({} as never),
    lockCut: async () => ({
      hash: "f".repeat(64), projectionHash: "e".repeat(64), reused: true,
      lock: { timelineMapHash: "d".repeat(64) },
    } as never),
    verifyCut: async () => ({
      gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0,
      metrics: { receipt: {
        stage: "planning_gate", planHash: "a".repeat(64),
        manifestHash: "b".repeat(64), transcriptDigest: "c".repeat(64),
        cutTrackDigest: "d".repeat(64), cutDecisionsDigest: "e".repeat(64),
      } },
    }),
    planning: (run) => reviewed(run, counts),
    baseGuard: async () => {},
    checkpoint: async () => ({ status: "committed" as const }),
    approvedMirror: async () => {},
    palmierPrimary: async () => false,
    renderGraphReady: () => true,
    approvedRevisionReady: () => true,
    initializeAuthority: () => ({
      status: "initialized" as const,
      revisionHash: "9".repeat(64),
    }),
    assemble: async (dir, _manifest, _send, outputPath) => {
      counts.assemble += 1;
      assert.ok(outputPath?.includes(`${path.sep}.sniper-qc${path.sep}`));
      writeAuthority(
        outputPath!, path.join(dir, "edit_plan.json"),
        `candidate-${counts.assemble}`,
      );
      return { code: 0, errTail: "" };
    },
    quality: async () => {
      counts.quality += 1;
      return {
        status: "approved" as const,
        finalHash: "approved-in-stub",
      };
    },
  };
}

export function checkpointApprovedJob(
  ctx: AutoEditCtx,
  token: string,
): AutoEditJob {
  startAutoEditJob({
    ctx, token, snapshots: 0,
    bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const planHash = fileSha256(ctx.planPath)!;
  const manifestHash = fileSha256(ctx.manifestPath)!;
  const final = path.join(ctx.dir, "final.mp4");
  const candidate = path.join(
    ctx.dir, ".sniper-qc", "manual", "round-1", "final.mp4");
  mkdirSync(path.dirname(candidate), { recursive: true });
  const finalHash = writeAuthority(candidate, ctx.planPath, "approved");
  const authority = autoEditAuthoritySnapshot(ctx);
  const approval = writeApprovalFixture({
    ctx, token, candidate, planningRoundsRequired: 1,
  });
  promoteApprovedCandidate(candidate, ctx.dir, approval);
  assert.equal(fileSha256(final), finalHash);
  const update: CheckpointUpdate = {
    checkpoint: "quality_check", phase: "quality_check",
    message: "approved", planHash, reviewedPlanHash: planHash, manifestHash,
    authorityDigest: authority.digest,
    reviewedAuthorityDigest: authority.digest,
    renderedPlanHash: planHash, renderedManifestHash: manifestHash,
    renderedAuthorityDigest: authority.digest,
    planningRound: 1, planningRoundsRequired: 1,
    qcRound: 1, finalHash,
  };
  advanceAutoEditJob(autoEditJobPath(ctx.dir), token, update);
  return readAutoEditJob(autoEditJobPath(ctx.dir))!;
}

export function checkpointRenderingJob(
  ctx: AutoEditCtx,
  token: string,
): AutoEditJob {
  startAutoEditJob({
    ctx, token, snapshots: 0,
    bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const planHash = fileSha256(ctx.planPath)!;
  const manifestHash = fileSha256(ctx.manifestPath)!;
  advanceAutoEditJob(autoEditJobPath(ctx.dir), token, {
    checkpoint: "rendering", phase: "rendering",
    message: "worker stopped while rendering candidate 1",
    planHash, reviewedPlanHash: planHash, manifestHash,
    planningRound: 2, planningRoundsRequired: 2,
    qcRound: 1, qcRoundsMax: 3,
  });
  return readAutoEditJob(autoEditJobPath(ctx.dir))!;
}
