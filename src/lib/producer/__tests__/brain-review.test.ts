import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { buildCodexArgs } from "../../../app/api/_lib/codex-cli";
import {
  buildClaudeBrainArgs,
  parseClaudeResultStream,
  runProducerGateFix,
  runProducerReview,
  runProducerRevision,
} from "../../../app/api/producer/auto-edit/brain-review-runner";
import { buildPlanReviewPrompt } from "../../../app/api/producer/auto-edit/plan-review-prompt";
import {
  bindPlanReviewPacket,
  buildPlanReviewPacket,
} from "../../../app/api/producer/auto-edit/plan-review-packet";
import type { GateBundleVerdict } from "../../../app/api/producer/auto-edit/planning-gates";
import { buildRenderedReviewPrompt } from "../../../app/api/producer/auto-edit/rendered-review-prompt";
import {
  parseProducerReview,
  parseRevisionReceipt,
  type ProducerReview,
} from "../../../app/api/producer/auto-edit/review-contract";
import { buildRevisionPrompt } from "../../../app/api/producer/auto-edit/revision-prompt";
import { producerRevisionJsonSchema } from
  "../../../app/api/producer/auto-edit/review-json-schemas";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import type { AutoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { fileSha256 } from "../../server/auto-edit-hash";
import { writeQualityJson } from "../../server/auto-edit-quality-artifacts";
import { captureAutoEditDoctrine } from "../../server/auto-edit-doctrine";
import { visualStorytellingInstructions } from "../visual-storytelling";

const testRoot = mkdtempSync(path.join(os.tmpdir(), "sniper-brain-review-"));
const producerDir = path.join(testRoot, "producer");
const sourceDir = path.join(testRoot, "source");
mkdirSync(producerDir, { recursive: true });
mkdirSync(sourceDir, { recursive: true });
writeFileSync(path.join(producerDir, "edit_plan.json"), '{"planVersion":1,"cutTrack":[]}');
writeFileSync(path.join(sourceDir, "asset_manifest.json"), '{"sources":[]}');

const baseCtx: AutoEditCtx = {
  dir: producerDir,
  scope: "produced",
  intent: { mode: "longform", brief: "Make the argument clear." },
  planPath: path.join(producerDir, "edit_plan.json"),
  manifestPath: path.join(sourceDir, "asset_manifest.json"),
  transcriptsDir: sourceDir,
};
const ctx: AutoEditCtx = {
  ...baseCtx,
  doctrine: captureAutoEditDoctrine(baseCtx, "brain-review-test", process.cwd()),
};

const PASS_GATES: GateBundleVerdict = {
  ok: true, errors: [], warnings: [],
  gates: {
    operatorIntent: { gate: "operator_intent", ok: true, errors: [], warnings: [], exit: 0 },
    transcriptCut: { gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0 },
    planLint: { gate: "plan_lint", ok: true, errors: [], warnings: [], exit: 0 },
    hookContract: { gate: "hook_contract", ok: true, errors: [], warnings: [], exit: 0 },
    templateUsage: { gate: "template_usage", ok: true, errors: [], warnings: [], exit: 0 },
    claimsContract: { gate: "claims_contract", ok: true, errors: [], warnings: [], exit: 0 },
    compSize: { gate: "comp_size", ok: true, errors: [], warnings: [], exit: 0 },
    geometryFeasibility: { gate: "geometry_feasibility", ok: true, errors: [], warnings: [], exit: 0 },
    referenceLint: null,
  },
};

const authority: AutoEditAuthoritySnapshot = {
  schemaVersion: 1, qualityPolicyVersion: 1,
  digest: "b".repeat(64),
  planHash: fileSha256(ctx.planPath)!, planContentHash: "c".repeat(64),
  manifestHash: fileSha256(ctx.manifestPath)!,
  operatorIntentDigest: "d".repeat(64), transcriptDigest: "e".repeat(64),
  referenceDigest: "f".repeat(64), pipelineDigest: "1".repeat(64),
};
const packetPath = path.join(
  producerDir, ".sniper-qc", "brain-review", "planning", "round-1",
  "critic-input-test", "plan-review-packet.json",
);
const packetValue = buildPlanReviewPacket(ctx, 1, PASS_GATES, authority);
const packet = bindPlanReviewPacket(writeQualityJson(packetPath, packetValue), packetValue);

const materialReview: ProducerReview = {
  schemaVersion: 1,
  stage: "plan",
  verdict: "revise",
  summary: "The full-screen card does not have enough evidence.",
  materialIssues: [{
    code: "PLAN_OWN_SCREEN_01",
    severity: "major",
    lane: "graphics",
    message: "The card is not grounded.",
    evidence: ["graphicsTrack[2] at 00:12.4"],
    requiredAction: "Remove it or ground it in kept transcript copy.",
  }],
  findings: [],
};

const passJson = JSON.stringify({
  schemaVersion: 1,
  stage: "plan",
  verdict: "pass",
  summary: "Plan is ready for deterministic rendering.",
  materialIssues: [],
  findings: [{
    code: "PLAN_NOTE_01",
    severity: "info",
    lane: "cuts",
    message: "The cold open is concise.",
    evidence: ["cutTrack[0]"],
  }],
});

const receiptJson = JSON.stringify({
  schemaVersion: 1,
  changedPlan: true,
  addressedIssueCodes: ["PLAN_OWN_SCREEN_01"],
  deferredIssueCodes: [],
  summary: "Removed the ungrounded card.",
});

function testStrictJsonBoundaries(): void {
  const fencedReview = ` \n\`\`\`json\n${passJson}\n\`\`\`\n`;
  assert.equal(parseProducerReview(fencedReview, "plan").verdict, "pass");
  assert.equal(parseProducerReview(`\`\`\`\n${passJson}\n\`\`\``, "plan").stage, "plan");
  assert.equal(parseRevisionReceipt(`\`\`\`json\n${receiptJson}\n\`\`\``).changedPlan, true);
  const invalid = [
    `Here is the review:\n\`\`\`json\n${passJson}\n\`\`\``,
    `\`\`\`json\n${passJson}\n\`\`\`\nDone.`,
    `${passJson}\n${passJson}`,
    `\`\`\`json\n${passJson}\n\`\`\`\n\`\`\`json\n${passJson}\n\`\`\``,
    `\`\`\`javascript\n${passJson}\n\`\`\``,
    `\`\`\`json\n{"schemaVersion":1,\n\`\`\``,
  ];
  invalid.forEach((value) => assert.throws(() => parseProducerReview(value, "plan")));
  assert.throws(() => parseRevisionReceipt(`${receiptJson}\ntrailing junk`));
}

function testSchemaAndParsers(): void {
  const schemaPath = path.join(process.cwd(), "schemas", "codex", "producer-review.schema.json");
  const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as Record<string, unknown>;
  assert.equal(schema.additionalProperties, false);
  const args = buildCodexArgs({
    sandbox: "read-only", timeoutMs: 10_000, schema: "producer-review",
  });
  assert.ok(args.some((arg) => arg.endsWith("schemas/codex/producer-review.schema.json")));
  assert.deepEqual(parseProducerReview(passJson, "plan").materialIssues, []);
  assert.throws(
    () => parseProducerReview(passJson.replace('"summary":', '"extra":true,"summary":')),
    /extra=extra/,
  );
  assert.throws(
    () => parseProducerReview(passJson.replace('"verdict":"pass"', '"verdict":"revise"')),
    /requires at least one materialIssue/,
  );
  const receipt = parseRevisionReceipt(receiptJson);
  assert.equal(receipt.changedPlan, true);
}

function testPromptsAndTools(): void {
  const plan = buildPlanReviewPrompt(ctx, 1, packet, packetValue);
  assert.ok(plan.includes(visualStorytellingInstructions("longform", "plan-review")));
  assert.match(plan, /FRESH, INDEPENDENT/);
  assert.match(plan, /remain READ-ONLY/);
  assert.match(plan, /Never edit, create, rename, or delete/);
  assert.match(plan, /"stage":"plan"/);
  assert.match(plan, /sole mutable-job evidence/i);
  assert.match(plan, /BEGIN_HASH_BOUND_PLAN_REVIEW_PACKET_JSON/);
  assert.match(plan, /BEGIN_PINNED_CRITIC_CONTEXT_JSON/);
  assert.match(plan, /Do NOT perform a prior-render, implementation, code/);
  assert.match(plan, /audit every graphicsDecisions receipt/);
  assert.match(plan, /first-catalog-entry selection/);
  assert.match(plan, /required beat as omit is a material defect/);
  assert.match(plan, /maximumFeasibleDistinctKinds/);
  assert.match(plan, /replacementWitnesses/);
  assert.match(plan, /reuseReason must quote this beat/);
  assert.match(plan, /require at least one real transition deliverable/);
  assert.match(plan, /cannot waive the checked transition lane/);
  assert.ok(!plan.includes(ctx.planPath));
  assert.ok(!plan.includes(ctx.manifestPath));
  assert.ok(!plan.includes(ctx.transcriptsDir));
  const visual = buildRenderedReviewPrompt(ctx, renderedEvidence(), 1, "composition",
    { frames: [{ path: `${ctx.dir}/audit_frames/graphic-01.png`, labels: ["#1 graphic-01"] }], reference: [] });
  assert.match(visual, /Inspect EVERY attached frame visually/);
  assert.match(visual, /NO filesystem, shell, browser/);
  assert.match(visual, /BEGIN_PINNED_RENDERED_REVIEW_EVIDENCE_JSON/);
  assert.match(visual, /Image 1\/1: #1 graphic-01/);
  assert.ok(visual.includes(visualStorytellingInstructions("longform", "rendered-review")));
  assert.match(visual, /missing gaze\/visual measurements/i);
  assert.match(visual, /"stage":"rendered"/);
  const revision = buildRevisionPrompt(ctx, materialReview, 3);
  assert.ok(revision.includes(visualStorytellingInstructions("longform")));
  assert.match(revision, /only production-file mutation/);
  assert.match(revision, /Do not self-approve/);
  assert.match(revision, /cutTrack and cutDecisions.*IMMUTABLE/);
  assert.match(revision, /Every decisionRequired Produced\/full beat must resolve/);
  assert.match(revision, /maximumFeasibleDistinctKinds/);
  assert.ok(revision.includes("PLAN_OWN_SCREEN_01"));
  assert.match(revision, /complete material-issue code set is exactly \["PLAN_OWN_SCREEN_01"\]/);
  assert.match(revision, /Minor\/info finding codes are observations only/);
  const revisionSchema = producerRevisionJsonSchema(["PLAN_OWN_SCREEN_01"]);
  const revisionProperties = revisionSchema.properties as Record<string, Record<string, unknown>>;
  assert.deepEqual(
    (revisionProperties.addressedIssueCodes.items as Record<string, unknown>).enum,
    ["PLAN_OWN_SCREEN_01"],
  );
  const readArgs = buildClaudeBrainArgs(plan, ctx, "review", [ctx.dir]);
  assert.equal(readArgs[readArgs.indexOf("--model") + 1], "opus");
  assert.equal(readArgs[readArgs.indexOf("--allowedTools") + 1], "Read,Glob,Grep");
  assert.equal(readArgs[readArgs.indexOf("--effort") + 1], "xhigh");
  const isolatedArgs = buildClaudeBrainArgs(plan, ctx, "isolated-review", []);
  assert.equal(isolatedArgs[isolatedArgs.indexOf("--tools") + 1], "");
  assert.equal(isolatedArgs[isolatedArgs.indexOf("--allowedTools") + 1], "");
  const writeArgs = buildClaudeBrainArgs(revision, ctx, "revision", [ctx.dir]);
  const allowed = writeArgs[writeArgs.indexOf("--allowedTools") + 1];
  assert.ok(allowed.includes(`Edit(${ctx.planPath})`));
  assert.ok(allowed.includes("brain-review-scratch"));
  assert.equal(writeArgs[writeArgs.indexOf("--effort") + 1], "xhigh");
  const gateFixArgs = buildClaudeBrainArgs(revision, ctx, "gate-fix", [ctx.dir]);
  assert.equal(gateFixArgs[gateFixArgs.indexOf("--effort") + 1], "low");
  // The mechanical gate fixer runs on Sonnet, not the Opus editing brain.
  assert.equal(gateFixArgs[gateFixArgs.indexOf("--model") + 1], "sonnet");
  assert.ok(gateFixArgs[gateFixArgs.indexOf("--allowedTools") + 1].includes(`Edit(${ctx.planPath})`));
  // Only established plan-mutating revision writers resume the brain session;
  // critics stay independent and the gate fixer stays minimal/sessionless.
  const sessionCtx: AutoEditCtx = {
    ...ctx,
    brainSessionId: "0f0e0d0c-0b0a-4908-8706-050403020100",
    brainSessionEstablished: true,
  };
  const resumedArgs = buildClaudeBrainArgs(revision, sessionCtx, "revision", [ctx.dir]);
  assert.equal(resumedArgs[resumedArgs.indexOf("--resume") + 1], sessionCtx.brainSessionId);
  assert.equal(buildClaudeBrainArgs(plan, sessionCtx, "isolated-review", []).indexOf("--resume"), -1);
  assert.equal(buildClaudeBrainArgs(plan, sessionCtx, "review", [ctx.dir]).indexOf("--resume"), -1);
  assert.equal(buildClaudeBrainArgs(revision, sessionCtx, "gate-fix", [ctx.dir]).indexOf("--resume"), -1);
  const unestablished = buildClaudeBrainArgs(
    revision, { ...sessionCtx, brainSessionEstablished: false }, "revision", [ctx.dir],
  );
  assert.equal(unestablished.indexOf("--resume"), -1);
  const structuredWriteArgs = buildClaudeBrainArgs(
    revision,
    ctx,
    "revision",
    [ctx.dir],
    { type: "object", properties: { changedPlan: { type: "boolean" } } },
  );
  assert.equal(structuredWriteArgs[structuredWriteArgs.indexOf("--json-schema") + 1],
    '{"type":"object","properties":{"changedPlan":{"type":"boolean"}}}');
}

function renderedEvidence(): { auditReportPath: string; framePaths: string[] } {
  const frame = `${ctx.dir}/audit_frames/graphic-01.png`, audit = `${ctx.dir}/audit_report.json`;
  mkdirSync(path.dirname(frame), { recursive: true });
  writeFileSync(frame, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64"));
  writeFileSync(audit, JSON.stringify({ frames: [{ path: frame }] }));
  return { auditReportPath: audit, framePaths: [frame] };
}

async function testCodexInvocations(): Promise<void> {
  let calls = 0;
  const reviewResult = await runProducerReview({ stage: "plan", ctx, round: 1, packet }, {
    provider: () => "codex",
    codex: async (options) => {
      calls += 1;
      assert.equal(options.sandbox, "read-only");
      assert.equal(options.schema, "producer-review");
      assert.equal(options.reasoning, "medium");
      assert.equal(options.timeoutMs, 20 * 60 * 1000);
      assert.equal(options.cwd, path.dirname(packet.path));
      assert.deepEqual(options.addDirs, []);
      assert.equal(options.tools, "none");
      assert.ok(!options.prompt.includes(ctx.planPath));
      assert.ok(!options.prompt.includes(ctx.manifestPath));
      return { message: passJson, stderr: "", ms: 11 };
    },
  });
  assert.equal(reviewResult.review.verdict, "pass");
  const renderedJson = passJson.replace('"stage":"plan"', '"stage":"rendered"');
  const renderedResult = await runProducerReview({
    stage: "rendered",
    ctx,
    round: 1,
    evidence: renderedEvidence(),
  }, {
    provider: () => "codex",
    codex: async (options) => {
      calls += 1;
      assert.equal(options.sandbox, "read-only");
      assert.equal(options.schema, "producer-review");
      assert.equal(options.reasoning, "medium");
      // Rendered lens critics get a 25-min cap — above the ~20-min measured max
      // so an Opus-xhigh vision critic isn't killed mid-reasoning.
      assert.equal(options.timeoutMs, 25 * 60 * 1000);
      assert.equal(options.cwd, ctx.dir);
      // Tool-less, no directory access, frames attached, OS media boundary on.
      assert.equal(options.tools, "none");
      assert.deepEqual(options.addDirs, []);
      assert.equal(options.jail, true);
      assert.deepEqual(options.imagePaths, [`${ctx.dir}/audit_frames/graphic-01.png`]);
      assert.ok(!options.prompt.includes("Rendered deliverable:"), "no video path is offered to the critic");
      return { message: renderedJson, stderr: "", ms: 11 };
    },
  });
  assert.equal(renderedResult.review.stage, "rendered");
  const revisionResult = await runProducerRevision(ctx, materialReview, 2, {
    provider: () => "codex",
    codex: async (options) => {
      calls += 1;
      assert.equal(options.sandbox, "workspace-write");
      assert.equal(options.schema, "producer-revision");
      assert.equal(options.reasoning, "medium");
      assert.equal(options.timeoutMs, 20 * 60 * 1000);
      assert.notEqual(options.cwd, ctx.dir);
      assert.match(options.prompt, /BEGIN_VALIDATED_CRITIQUE_JSON/);
      writeFileSync(path.join(options.cwd!, "edit_plan.json"), JSON.stringify({
        planVersion: 2,
        cutTrack: [{ sourceId: "source-1", start: 0, end: 1 }],
      }));
      return { message: receiptJson, stderr: "", ms: 12 };
    },
  });
  assert.equal(revisionResult.receipt.addressedIssueCodes[0], "PLAN_OWN_SCREEN_01");
  assert.equal(JSON.parse(readFileSync(ctx.planPath, "utf8")).planVersion, 2);
  await assert.rejects(
    runProducerRevision(ctx, materialReview, 3, {
      provider: () => "codex",
      codex: async (options) => {
        calls += 1;
        assert.equal(options.reasoning, "medium");
        writeFileSync(path.join(options.cwd!, "edit_plan.json"), JSON.stringify({
          planVersion: 3,
          cutTrack: [{ sourceId: "source-1", start: 0, end: 1 }],
        }));
        return { message: receiptJson, stderr: "", ms: 13 };
      },
    }),
    /receipt claimed a plan change, but staged edit_plan\.json had no render-affecting change/,
  );
  assert.equal(JSON.parse(readFileSync(ctx.planPath, "utf8")).planVersion, 2);
  const gateFixResult = await runProducerGateFix(ctx, materialReview, 4, {
    provider: () => "codex",
    codex: async (options) => {
      calls += 1;
      assert.equal(options.sandbox, "workspace-write");
      assert.equal(options.schema, "producer-revision");
      assert.equal(options.reasoning, "low");
      assert.equal(options.timeoutMs, 6 * 60 * 1000);
      assert.match(options.prompt, /PRODUCER GATE FIXER/);
      // Minimal packet: machine diagnostics + the plan — no doctrine re-read.
      assert.ok(!options.prompt.includes("SKILL.md"));
      assert.ok(!options.prompt.includes("FAILURE_LEDGER.md"));
      writeFileSync(path.join(options.cwd!, "edit_plan.json"), JSON.stringify({
        planVersion: 4,
        cutTrack: [{ sourceId: "source-1", start: 0, end: 2 }],
      }));
      return { message: receiptJson, stderr: "", ms: 14 };
    },
  });
  assert.equal(gateFixResult.receipt.changedPlan, true);
  assert.equal(JSON.parse(readFileSync(ctx.planPath, "utf8")).planVersion, 4);
  assert.equal(calls, 5, "each plan/rendered critic and writer invokes a fresh CLI process runner");
}

async function testLegacyInvocation(): Promise<void> {
  const renderedJson = passJson.replace('"stage":"plan"', '"stage":"rendered"');
  const initialPlan = readFileSync(ctx.planPath, "utf8");
  let calls = 0;
  const planResult = await runProducerReview({
    stage: "plan", ctx, round: 1, packet,
  }, {
    provider: () => "legacy",
    legacy: async (invocation) => {
      calls += 1;
      assert.equal(invocation.cwd, path.dirname(packet.path));
      assert.equal(invocation.args[invocation.args.indexOf("--tools") + 1], "");
      assert.equal(invocation.args[invocation.args.indexOf("--allowedTools") + 1], "");
      assert.ok(invocation.args.some((arg) => arg.includes("BEGIN_HASH_BOUND_PLAN_REVIEW_PACKET_JSON")));
      return { message: passJson, stderr: "", ms: 8 };
    },
  });
  assert.equal(planResult.review.stage, "plan");
  const result = await runProducerReview({
    stage: "rendered",
    ctx,
    round: 1,
    evidence: renderedEvidence(),
  }, {
    provider: () => "legacy",
    legacy: async (invocation) => {
      calls += 1;
      assert.equal(invocation.cwd, ctx.dir);
      assert.equal(invocation.args[invocation.args.indexOf("--tools") + 1], "");
      assert.equal(invocation.args[invocation.args.indexOf("--allowedTools") + 1], "");
      assert.equal(invocation.args[invocation.args.indexOf("--input-format") + 1], "stream-json");
      assert.ok(!invocation.args.includes("--add-dir"));
      assert.equal(invocation.jail, true);
      const input = JSON.parse(invocation.stdin!) as { message: { content: Array<{ type: string }> } };
      assert.deepEqual(input.message.content.map((block) => block.type), ["text", "image"]);
      return { message: renderedJson, stderr: "", ms: 9 };
    },
  });
  assert.equal(result.review.stage, "rendered");
  await runProducerRevision(ctx, materialReview, 1, {
    provider: () => "legacy",
    legacy: async (invocation) => {
      calls += 1;
      const schemaAt = invocation.args.indexOf("--json-schema");
      const schema = JSON.parse(invocation.args[schemaAt + 1]) as {
        properties: { addressedIssueCodes: { items: { enum: string[] } } };
      };
      assert.deepEqual(
        schema.properties.addressedIssueCodes.items.enum,
        ["PLAN_OWN_SCREEN_01"],
      );
      writeFileSync(path.join(invocation.cwd, "edit_plan.json"), JSON.stringify({
        planVersion: 2,
        cutTrack: [{ sourceId: "source-1", start: 0, end: 1 }],
      }));
      return { message: receiptJson, stderr: "", ms: 10 };
    },
  });
  writeFileSync(ctx.planPath, initialPlan);
  assert.equal(calls, 3);
  assert.equal(
    parseClaudeResultStream(`{"type":"system"}\n${JSON.stringify({ type: "result", result: passJson })}\n`),
    passJson,
  );
  assert.equal(
    parseClaudeResultStream(`${JSON.stringify({
      type: "result",
      result: "prose must not win",
      structured_output: JSON.parse(passJson),
    })}\n`),
    passJson,
  );
}

testSchemaAndParsers();
testStrictJsonBoundaries();
testPromptsAndTools();
testLegacyInvocation()
  .then(testCodexInvocations)
  .then(() => console.log("brain-review.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(() => rmSync(testRoot, { recursive: true, force: true }));
