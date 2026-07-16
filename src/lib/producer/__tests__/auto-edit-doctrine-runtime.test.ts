import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { buildAuthoringPrompt } from "../../../app/api/producer/auto-edit/authoring-prompt";
import { buildPlanReviewPrompt } from "../../../app/api/producer/auto-edit/plan-review-prompt";
import { buildPlanReviewPacket } from "../../../app/api/producer/auto-edit/plan-review-packet";
import type { GateBundleVerdict } from "../../../app/api/producer/auto-edit/planning-gates";
import { buildRenderedReviewPrompt } from "../../../app/api/producer/auto-edit/rendered-review-prompt";
import { buildRevisionPrompt } from "../../../app/api/producer/auto-edit/revision-prompt";
import type { ProducerReview } from "../../../app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  autoEditAuthoritySnapshot,
} from "../../server/auto-edit-authority-snapshot";
import {
  captureAutoEditDoctrine,
  doctrinePromptPath,
  PRODUCER_CORE_DOCTRINE_PATHS,
  PRODUCER_REFERENCED_DOCTRINE_PATHS,
  prepareAutoEditDoctrineContext,
  restoreAutoEditDoctrine,
} from "../../server/auto-edit-doctrine";
import {
  persistAutoEditAuditOutcome,
  persistCriticObservations,
} from "../../server/auto-edit-observations";
import {
  autoEditJobPath,
  failAutoEditJob,
  readAutoEditJob,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";

const PASS_GATES: GateBundleVerdict = {
  ok: true, errors: [], warnings: [],
  gates: {
    operatorIntent: { gate: "operator_intent", ok: true, errors: [], warnings: [], exit: 0 },
    transcriptCut: { gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0 },
    planLint: { gate: "plan_lint", ok: true, errors: [], warnings: [], exit: 0 },
    hookContract: { gate: "hook_contract", ok: true, errors: [], warnings: [], exit: 0 },
    templateUsage: { gate: "template_usage", ok: true, errors: [], warnings: [], exit: 0 },
    claimsContract: { gate: "claims_contract", ok: true, errors: [], warnings: [], exit: 0 },
    referenceLint: null,
  },
};

function fixture(root: string): { repo: string; ctx: AutoEditCtx } {
  const repo = path.join(root, "repo");
  const dir = path.join(root, "project", "producer");
  const source = path.join(root, "project", "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  for (const relative of [
    ...PRODUCER_CORE_DOCTRINE_PATHS,
    ...PRODUCER_REFERENCED_DOCTRINE_PATHS,
  ]) {
    const destination = path.join(repo, relative);
    mkdirSync(path.dirname(destination), { recursive: true });
    writeFileSync(destination, `PINNED ${relative}\n`);
  }
  for (const relative of [
    "docs/studies/CALEB_STYLE.md",
    "scripts/producer/docs/findings/JADEN_STYLE.md",
    "docs/studies/ANGELA_STYLE.md",
  ]) {
    const destination = path.join(repo, relative);
    mkdirSync(path.dirname(destination), { recursive: true });
    writeFileSync(destination, `PINNED ${relative}\n`);
  }
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, '{"planVersion":1,"target":{"mode":"longform"},"cutTrack":[]}');
  writeFileSync(manifestPath, '{"sources":[]}');
  return {
    repo,
    ctx: {
      dir, scope: "produced", planPath, manifestPath, transcriptsDir: source,
      intent: { mode: "longform", lanes: {} },
    },
  };
}

function materialReview(): ProducerReview {
  return {
    schemaVersion: 1,
    stage: "plan",
    verdict: "revise",
    summary: "A transition is not motivated.",
    materialIssues: [{
      code: "TRANSITION_UNEARNED",
      severity: "major",
      lane: "transitions",
      message: "The wipe does not mark a semantic boundary.",
      evidence: ["edit_plan.json transition 1 at 00:12"],
      requiredAction: "Remove the wipe.",
    }],
    findings: [],
  };
}

function testLiveDriftKeepsPinnedPromptAuthority(root: string): void {
  const { repo, ctx } = fixture(path.join(root, "pin"));
  const doctrine = captureAutoEditDoctrine(ctx, "run-pinned", repo);
  const pinned = { ...ctx, doctrine, templateUsage: {
    schemaVersion: 1 as const,
    path: path.join(ctx.dir, ".sniper-learning/runs/run-pinned/template-usage.json"),
    digest: "a".repeat(64),
  } };
  const authorityBeforeDrift = restoreAutoEditDoctrine(doctrine).doctrineHash;
  const liveSkill = path.join(repo, ".agents/skills/producer/SKILL.md");
  writeFileSync(liveSkill, "LIVE DRIFT MUST NOT ENTER THIS RUN\n");
  assert.equal(restoreAutoEditDoctrine(doctrine).doctrineHash, authorityBeforeDrift);
  assert.equal(readFileSync(doctrinePromptPath(pinned, PRODUCER_CORE_DOCTRINE_PATHS[0]), "utf8"),
    `PINNED ${PRODUCER_CORE_DOCTRINE_PATHS[0]}\n`);
  const packet = {
    path: path.join(ctx.dir, ".sniper-qc/run/planning/round-1/critic-input/plan-review-packet.json"),
    hash: "1".repeat(64), contentDigest: "2".repeat(64),
    authorityDigest: "3".repeat(64), gateDigest: "4".repeat(64), round: 1,
  };
  const packetValue = buildPlanReviewPacket(
    pinned, 1, PASS_GATES, autoEditAuthoritySnapshot(pinned),
  );
  const prompts = [
    buildAuthoringPrompt(pinned, "codex"),
    buildPlanReviewPrompt(pinned, 1, packet, packetValue),
    buildRevisionPrompt(pinned, materialReview(), 1),
    buildRenderedReviewPrompt(pinned, {
      auditReportPath: path.join(ctx.dir, "audit_report.json"),
      framePaths: [path.join(ctx.dir, "frame-1.png")],
    }, 1),
  ];
  for (const prompt of prompts) {
    assert.ok(prompt.includes(doctrine.files[PRODUCER_CORE_DOCTRINE_PATHS[0]]));
    assert.ok(prompt.includes(doctrine.files[PRODUCER_CORE_DOCTRINE_PATHS[3]]));
    assert.ok(!prompt.includes(liveSkill));
  }
  assert.equal(restoreAutoEditDoctrine(doctrine).doctrineHash, doctrine.doctrineHash);
}

function testResumeRestores(root: string): void {
  const { repo, ctx } = fixture(path.join(root, "resume"));
  const doctrine = captureAutoEditDoctrine(ctx, "logical-run", repo);
  const pinned = { ...ctx, doctrine };
  const first = startAutoEditJob({ ctx: pinned, token: "worker-a", snapshots: 0 });
  failAutoEditJob(autoEditJobPath(ctx.dir), first.token, "test interruption");
  const saved = readAutoEditJob(autoEditJobPath(ctx.dir))!;
  writeFileSync(path.join(repo, PRODUCER_CORE_DOCTRINE_PATHS[3]), "new next-run lesson\n");
  const restored = restoreAutoEditDoctrine(saved.ctx.doctrine!);
  const resumed = startAutoEditJob({
    ctx: { ...ctx, doctrine: restored }, token: "worker-b", snapshots: 0, resume: saved,
  });
  assert.equal(resumed.ctx.doctrine?.runId, "logical-run");
  assert.equal(resumed.ctx.doctrine?.doctrineHash, doctrine.doctrineHash);
  assert.equal(resumed.artifactToken, "worker-a");
}

function testSelectedStyleDoctrineIsPinned(root: string): void {
  const { repo, ctx } = fixture(path.join(root, "style"));
  const styled: AutoEditCtx = {
    ...ctx,
    intent: { ...ctx.intent!, mode: "short", style: "caleb" },
  };
  const doctrine = captureAutoEditDoctrine(styled, "style-run", repo);
  assert.equal(
    readFileSync(doctrine.files["docs/studies/CALEB_STYLE.md"], "utf8"),
    "PINNED docs/studies/CALEB_STYLE.md\n",
  );
}

function testPromotedReferenceTeachingsArePinned(root: string): void {
  const { repo, ctx } = fixture(path.join(root, "reference-teachings"));
  const doctrine = captureAutoEditDoctrine(ctx, "reference-teachings-run", repo);
  for (const relative of [
    "docs/studies/EDITCRAFT_LESSONS.md",
    "docs/studies/NATEHERK_CARDS.md",
    "docs/studies/NATEHERK_STUDY.md",
    "docs/studies/REFERENCE_STYLE_STUDY.md",
    "docs/studies/SHORTFORM_LESSONS.md",
    "scripts/producer/docs/findings/REFERENCE_EVIDENCE_IS_NOT_TEMPLATE_AUTHORITY.md",
  ]) {
    assert.equal(readFileSync(doctrine.files[relative], "utf8"), `PINNED ${relative}\n`);
  }
}

function testTamperFails(root: string): void {
  const { repo, ctx } = fixture(path.join(root, "tamper"));
  const doctrine = captureAutoEditDoctrine(ctx, "tamper-run", repo);
  writeFileSync(doctrine.files[PRODUCER_CORE_DOCTRINE_PATHS[3]], "tampered copy\n");
  assert.throws(() => restoreAutoEditDoctrine(doctrine), /doctrine copy was changed/);
}

function testModernResumeRequiresItsSavedLock(root: string): void {
  const { ctx } = fixture(path.join(root, "missing-resume-lock"));
  assert.throws(() => prepareAutoEditDoctrineContext({
    ctx, runId: "new-token", resume: true,
  }), /predates immutable doctrine locking/);
}

function testObservationPersistence(root: string): void {
  const { repo, ctx } = fixture(path.join(root, "observations"));
  const doctrine = captureAutoEditDoctrine(ctx, "learning-run", repo);
  const pinned = { ...ctx, doctrine };
  const reviewPath = path.join(ctx.dir, "plan-review.json");
  writeFileSync(reviewPath, JSON.stringify(materialReview()));
  const critic = persistCriticObservations({
    ctx: pinned, artifactPath: reviewPath, review: materialReview(), namespace: "planning-a1-r1",
  });
  assert.equal(critic.length, 1);
  const candidateDir = path.join(ctx.dir, ".sniper-qc", "learning-run", "round-1");
  mkdirSync(candidateDir, { recursive: true });
  const machine = path.join(candidateDir, "audit_report.json");
  writeFileSync(machine, JSON.stringify({ checks: [
    { name: "motion_pacing", status: "warn", measured: "gap 18s", detail: "too static" },
    { name: "true_peak", status: "fail", measured: "+0.3 dBTP", detail: "clipping" },
    { name: "black_frames", status: "pass" },
  ] }));
  const qc = persistAutoEditAuditOutcome({
    ctx: pinned,
    candidateDir,
    round: 1,
    attempt: 1,
    audit: {
      event: { event: "audit", overall: "fail", machine },
      failure: "true peak failed",
    },
  });
  assert.equal(qc.length, 2);
  const observations = path.join(ctx.dir, ".sniper-learning", "runs", "learning-run", "observations");
  assert.equal(readdirSync(observations).length, 3);
  for (const name of readdirSync(observations)) {
    const value = JSON.parse(readFileSync(path.join(observations, name), "utf8"));
    assert.equal(value.runId, "learning-run");
    assert.equal(value.doctrineHash, doctrine.doctrineHash);
    assert.equal(value.status, "observed");
    assert.ok(!JSON.stringify(value).includes("lessonText"));
  }
  assert.equal(persistCriticObservations({
    ctx: pinned, artifactPath: reviewPath, review: materialReview(), namespace: "planning-a1-r1",
  }).length, 1, "identical observation persistence is idempotent");
}

function main(): void {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-doctrine-runtime-"));
  try {
    testLiveDriftKeepsPinnedPromptAuthority(root);
    testResumeRestores(root);
    testSelectedStyleDoctrineIsPinned(root);
    testPromotedReferenceTeachingsArePinned(root);
    testTamperFails(root);
    testModernResumeRequiresItsSavedLock(root);
    testObservationPersistence(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-doctrine-runtime.test.ts: all assertions passed");
}

main();
