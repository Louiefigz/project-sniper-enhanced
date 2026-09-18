import assert from "node:assert/strict";
import {
  mkdtempSync, readFileSync, rmSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runProducerReview,
  runProducerRevision,
} from "../../../app/api/producer/auto-edit/brain-review-runner";
import {
  bindCutReviewPacket,
  buildCutReviewPacket,
} from "../../../app/api/producer/auto-edit/cut-review-packet";
import { buildCutReviewPrompt } from
  "../../../app/api/producer/auto-edit/cut-review-prompt";
import {
  cutReviewApprovalPath,
  persistCutReviewApproval,
  verifyCutReviewApproval,
  type CleanCutReviewArtifact,
} from "../../../app/api/producer/auto-edit/cut-review-approval";
import type { ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  autoEditAuthoritySnapshot,
} from "../../server/auto-edit-authority-snapshot";
import { fileSha256 } from "../../server/auto-edit-hash";
import { writeQualityJson } from "../../server/auto-edit-quality-artifacts";
import { cutReviewFixture as fixture, cutReviewGate as gate } from "./_cut-review-contract-fixture";

const passReview: ProducerReview = {
  schemaVersion: 1, stage: "cut", verdict: "pass",
  summary: "The transcript spine is coherent and complete.",
  materialIssues: [], findings: [],
};

const materialReview: ProducerReview = {
  schemaVersion: 1, stage: "cut", verdict: "revise",
  summary: "A repeated phrase should be removed.",
  materialIssues: [{
    code: "CUT_REPEAT_01", severity: "major", lane: "cuts",
    message: "The same phrase occurs twice.", evidence: ["output 00:01"],
    requiredAction: "Remove the weaker repeat at a word-safe boundary.",
  }],
  findings: [],
};

function receiptJson(): string {
  return JSON.stringify({
    schemaVersion: 1, changedPlan: true,
    addressedIssueCodes: ["CUT_REPEAT_01"], deferredIssueCodes: [],
    summary: "Removed the weaker repeat.",
  });
}

function deferredReceiptJson(): string {
  return JSON.stringify({
    schemaVersion: 1, changedPlan: false,
    addressedIssueCodes: [], deferredIssueCodes: ["CUT_REPEAT_01"],
    summary: "Critique conflicts with deterministic cut evidence; plan unchanged.",
  });
}

async function testReview(ctx: AutoEditCtx): Promise<void> {
  const authority = autoEditAuthoritySnapshot(ctx);
  const packetValue = buildCutReviewPacket(ctx, 1, gate(ctx), authority);
  const packetPath = path.join(
    ctx.dir, ".sniper-qc", "cut-contract", "cut", "round-1",
    "critic-input-test", "cut-review-packet.json",
  );
  const packet = bindCutReviewPacket(writeQualityJson(packetPath, packetValue), packetValue);
  const prompt = buildCutReviewPrompt(ctx, 1, packet, packetValue);
  assert.match(prompt, /FRESH, INDEPENDENT TRANSCRIPT CUT CRITIC/);
  assert.match(prompt, /adjacent repeated words\/phrases/);
  assert.match(prompt, /unfinished tails/);
  assert.equal(packetValue.keptSpeech.fullText, "This is the complete opening thought.");
  assert.match(prompt, /a boundary "before" word is NOT kept/);
  assert.match(prompt, /forbiddenOpeningStarts/);
  assert.match(prompt, /not a prohibition on restoration/);
  assert.match(prompt, /source-grounded human audio\/boundary review/);
  assert.match(prompt, /not proof of the audio actually heard/);
  assert.match(prompt, /Do not move a boundary merely to make a quality gate pass/);
  assert.doesNotMatch(prompt, /Never require reintroducing one of those spans/);
  assert.doesNotMatch(prompt, /uncertainty only as a minor finding/);
  assert.doesNotMatch(prompt, /dead air must be removed/);
  const doctrineJson = prompt.split("BEGIN_PINNED_CUT_DOCTRINE_JSON\n")[1]
    .split("\nEND_PINNED_CUT_DOCTRINE_JSON")[0];
  const labels = (JSON.parse(doctrineJson) as Array<{ label: string }>)
    .map((row) => row.label);
  assert.deepEqual(labels, [
    ".agents/skills/producer/SKILL.md",
    ".claude/skills/producer/SKILL.md",
    "scripts/producer/docs/findings/FAILURE_LEDGER.md",
  ]);
  const result = await runProducerReview({ stage: "cut", ctx, round: 1, packet }, {
    provider: () => "codex",
    codex: async (options) => {
      assert.equal(options.sandbox, "read-only");
      assert.equal(options.tools, "none");
      assert.equal(options.cwd, path.dirname(packetPath));
      return { message: JSON.stringify(passReview), stderr: "", ms: 4 };
    },
  });
  assert.equal(result.review.stage, "cut");
  assert.equal(result.review.verdict, "pass");
}

async function testCutOnlyRevision(ctx: AutoEditCtx): Promise<void> {
  await runProducerRevision(ctx, materialReview, 1, {
    provider: () => "codex",
    codex: async (options) => {
      const plan = JSON.parse(readFileSync(path.join(options.cwd!, "edit_plan.json"), "utf8"));
      writeFileSync(path.join(options.cwd!, "edit_plan.json"), JSON.stringify({
        ...plan, planVersion: 2,
        cutTrack: [{ ...plan.cutTrack[0], end: 2 }],
      }));
      return { message: receiptJson(), stderr: "", ms: 4 };
    },
  });
  const approvedHash = fileSha256(ctx.planPath);
  assert.equal(JSON.parse(readFileSync(ctx.planPath, "utf8")).cutTrack[0].end, 2);
  await assert.rejects(runProducerRevision(ctx, materialReview, 2, {
    provider: () => "codex",
    codex: async (options) => {
      const plan = JSON.parse(readFileSync(path.join(options.cwd!, "edit_plan.json"), "utf8"));
      writeFileSync(path.join(options.cwd!, "edit_plan.json"), JSON.stringify({
        ...plan, planVersion: 3,
        target: { ...plan.target, mode: "short", durationTargetS: 1.8 },
      }));
      return { message: receiptJson(), stderr: "", ms: 4 };
    },
  }), /cut revision changed protected plan field: target/);
  assert.equal(fileSha256(ctx.planPath), approvedHash, "rejected staging output must not promote");
  const deferred = await runProducerRevision(ctx, materialReview, 3, {
    provider: () => "codex",
    codex: async () => ({ message: deferredReceiptJson(), stderr: "", ms: 4 }),
  });
  assert.equal(deferred.receipt.changedPlan, false);
  assert.deepEqual(deferred.receipt.deferredIssueCodes, ["CUT_REPEAT_01"]);
  assert.equal(fileSha256(ctx.planPath), approvedHash, "deferred no-op must preserve plan bytes");
  await assert.rejects(runProducerRevision(ctx, materialReview, 4, {
    provider: () => "codex",
    codex: async () => ({ message: receiptJson(), stderr: "", ms: 4 }),
  }), /receipt claimed a plan change, but staged edit_plan\.json had no render-affecting change/);
}

function testReviewApproval(ctx: AutoEditCtx): void {
  const authority = autoEditAuthoritySnapshot(ctx);
  const originalPlan = readFileSync(ctx.planPath, "utf8");
  const transcriptPath = path.join(ctx.transcriptsDir, "raw.transcript.json");
  const originalTranscript = readFileSync(transcriptPath, "utf8");
  const reviews: CleanCutReviewArtifact[] = [1, 2].map((round) => {
    const packetPath = writeQualityJson(
      path.join(ctx.dir, ".sniper-qc", "cut-contract", "cut", `round-${round}`,
        "critic-input-test", "cut-review-packet.json"),
      {
        schemaVersion: 1,
        stage: "cut",
        doctrineHash: ctx.doctrine?.doctrineHash ?? null,
        request: { scope: ctx.scope, operatorIntent: ctx.intent ?? null },
        inputAuthority: authority,
      },
    );
    const artifactPath = writeQualityJson(
      path.join(ctx.dir, ".sniper-qc", "cut-contract", "cut", `round-${round}`, "cut-review.json"),
      {
        schemaVersion: 1, stage: "cut", round,
        inputAuthority: authority,
        inputPacket: { path: packetPath, hash: fileSha256(packetPath)! },
        review: passReview,
      },
    );
    return { round, path: artifactPath, hash: fileSha256(artifactPath)! };
  });
  const stored = persistCutReviewApproval(ctx, gate(ctx), authority.digest, reviews);
  assert.equal(stored.reviews.length, 2);
  assert.equal(verifyCutReviewApproval(ctx, gate(ctx)).cutAuthorityDigest,
    stored.cutAuthorityDigest);
  const duplicateCases: Array<[string, CleanCutReviewArtifact[]]> = [
    ["rounds", [reviews[0], { ...reviews[1], round: reviews[0].round }]],
    ["artifact paths", [reviews[0], { ...reviews[1], path: reviews[0].path }]],
    ["hashes", [reviews[0], { ...reviews[1], hash: reviews[0].hash }]],
  ];
  for (const [label, duplicated] of duplicateCases) {
    writeFileSync(cutReviewApprovalPath(ctx), JSON.stringify({
      ...stored, reviews: duplicated,
    }));
    assert.throws(
      () => verifyCutReviewApproval(ctx, gate(ctx)),
      new RegExp(`requires distinct ${label}`),
    );
  }
  writeFileSync(cutReviewApprovalPath(ctx), JSON.stringify(stored));

  const plan = JSON.parse(originalPlan);
  writeFileSync(ctx.planPath, JSON.stringify({
    ...plan, planVersion: 2,
    graphicsTrack: [{ id: "proof", outStart: 0.4, outEnd: 2.2, form: "statement-card" }],
    motionTrack: [{ id: "punch", outStart: 1, outEnd: 1.6, kind: "punch" }],
  }));
  assert.doesNotThrow(() => verifyCutReviewApproval(ctx, gate(ctx)),
    "downstream visual lanes must not invalidate an unchanged approved cut");

  const approvedIntent = ctx.intent;
  ctx.intent = { ...ctx.intent, mode: "short" };
  assert.throws(() => verifyCutReviewApproval(ctx, gate(ctx)), /current cut authority/,
    "short/long intent drift must invalidate reviews made for another editorial contract");
  ctx.intent = approvedIntent;

  const legacy = { ...stored } as Partial<typeof stored>;
  delete legacy.qualityPolicyVersion;
  delete legacy.doctrineHash;
  delete legacy.cutIntentDigest;
  delete legacy.cutAuthorityDigest;
  writeFileSync(cutReviewApprovalPath(ctx), JSON.stringify(legacy));
  assert.doesNotThrow(() => verifyCutReviewApproval(ctx, gate(ctx)),
    "legacy cut-only receipts must upgrade without repeating clean reviews");
  assert.match(JSON.parse(readFileSync(cutReviewApprovalPath(ctx), "utf8")).cutAuthorityDigest,
    /^[a-f0-9]{64}$/);

  const visualPlan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  writeFileSync(ctx.planPath, JSON.stringify({
    ...visualPlan,
    cutTrack: [{ ...visualPlan.cutTrack[0], end: 2.2 }],
  }));
  assert.throws(() => verifyCutReviewApproval(ctx, gate(ctx)), /current cut authority/);
  writeFileSync(ctx.planPath, JSON.stringify(visualPlan));

  writeFileSync(transcriptPath, `${originalTranscript}\n`);
  assert.throws(() => verifyCutReviewApproval(ctx, gate(ctx)), /current cut authority/);
  writeFileSync(transcriptPath, originalTranscript);

  const originalManifest = readFileSync(ctx.manifestPath, "utf8");
  writeFileSync(ctx.manifestPath, `${originalManifest}\n`);
  assert.throws(() => verifyCutReviewApproval(ctx, gate(ctx)), /current cut authority/);
  writeFileSync(ctx.manifestPath, originalManifest);
  writeFileSync(ctx.planPath, originalPlan);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-cut-review-contract-"));
  try {
    const ctx = fixture(root);
    await testReview(ctx);
    testReviewApproval(ctx);
    await testCutOnlyRevision(ctx);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("cut-review-contract.test.ts: all assertions passed");
}

void main();
