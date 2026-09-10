import assert from "node:assert/strict";
import { test } from "node:test";
import { assertStoredProposalEvidence, proposalIntroSeams, PROPOSAL_HOOK_WINDOW_S, type ProposalEvidence } from "../guided-proposal-evidence";
import { buildProposalPrompt, runProposalBrain } from "../guided-proposal-compiler";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

const segment = (index: number, startFrame: number, endFrameExclusive: number) =>
  ({ index, sourceId: "s", startFrame, endFrameExclusive, text: "" });

test("intro seam evidence is every internal cut boundary strictly inside the long-form hook window", () => {
  const segments = [segment(0, 0, 900), segment(1, 900, 1500), segment(2, 1500, 1800), segment(3, 1800, 2700), segment(4, 2700, 3600)];
  assert.deepEqual(proposalIntroSeams(segments, "30/1"), [{ seamIndex: 0, outTime: 30, startFrame: 900 },
    { seamIndex: 1, outTime: 50, startFrame: 1500 }]);
  assert.equal(PROPOSAL_HOOK_WINDOW_S, 60);
  assert.deepEqual(proposalIntroSeams([segment(0, 0, 3600)], "30/1"), []);
  const drop = proposalIntroSeams([segment(0, 0, 1798), segment(1, 1798, 3600)], "30000/1001");
  assert.equal(drop.length, 1);
  assert.ok(Math.abs(drop[0].outTime - 1798 * 1001 / 30000) < 1e-9);
  assert.throws(() => proposalIntroSeams(segments, "30"), /exact rational frame rate/);
});

test("stored V4 evidence must carry exactly the seam and presentation fields the compile path writes", () => {
  const base = { schemaVersion: 4, cutDecisionHash: "a", parentRevisionHash: "b", timelineMapHash: "c", frameRate: "30/1",
    totalFrames: 900, target: {}, segments: [], catalog: [], catalogHash: "d", graphicsAdvice: {}, doctrine: [], pipelineHash: "e",
    occurrences: [], anchors: [], cleanEnds: [], wordTupleFields: [], wordTimingScope: "x", scope: "y", presentationPolicy: {} };
  const cut = { job: { ctx: {} } } as unknown as AcceptedGuidedCut, staged = {} as Parameters<typeof assertStoredProposalEvidence>[2];
  assert.throws(() => assertStoredProposalEvidence(cut, base as unknown as ProposalEvidence, staged), /missing fields: introSeams, hookWindowS/);
  const full = { ...base, introSeams: [], hookWindowS: 60 } as unknown as ProposalEvidence;
  assert.throws(() => assertStoredProposalEvidence(cut, full, staged), /Proposal doctrine is absent/);
  assert.throws(() => assertStoredProposalEvidence(cut, { ...full, extra: 1 } as unknown as ProposalEvidence, staged), /unsupported fields: extra/);
  const older = { ...base, schemaVersion: 3 } as unknown as ProposalEvidence;
  assert.throws(() => assertStoredProposalEvidence(cut, older, staged), /Proposal doctrine is absent/);
  assert.throws(() => assertStoredProposalEvidence(cut, { ...older, introSeams: [] } as unknown as ProposalEvidence, staged), /unsupported fields: introSeams/);
});

test("only V4 evidence receives the produced-longform decision doctrine, and it names the exact gate fields", () => {
  const evidence = { schemaVersion: 4, hookWindowS: 60, anchors: [0, 1], introSeams: [] } as unknown as ProposalEvidence;
  const prompt = buildProposalPrompt("Keep the cut.", evidence);
  for (const rule of ["graphicsStyle", "graphicsStyleRationale", "decisionRequired", "compatibleKinds", "alternativesConsidered",
    "selectionReason", "minimumGraphicHoldS", "formAllocation.recommendedAssignment", "hookSeamDecisions", "clean-hook",
    "face-bridge", "60s hook window", "V3 requires presentation on EVERY operation"]) {
    assert.ok(prompt.includes(rule), `V4 doctrine is missing ${rule}`);
  }
  const v3 = buildProposalPrompt("Keep the cut.", { ...evidence, schemaVersion: 3 } as unknown as ProposalEvidence);
  assert.ok(!v3.includes("hookSeamDecisions"));
  assert.ok(v3.includes("V3 requires presentation on EVERY operation"));
  assert.ok(!buildProposalPrompt("Keep the cut.", { ...evidence, schemaVersion: 2 } as unknown as ProposalEvidence).includes("presentation on EVERY"));
});

test("the captured schema object selects its own registered structured-output name", async () => {
  const prior = process.env.SNIPER_BRAIN_PROVIDER;
  try {
    process.env.SNIPER_BRAIN_PROVIDER = "codex";
    const observed: string[] = [];
    for (const version of [2, 3, 4]) {
      await runProposalBrain({ prompt: "TEST ONLY", ctx: {} as AutoEditCtx, cwd: "/private/tmp", timeoutMs: 500,
        schema: { properties: { schemaVersion: { const: version } } } }, { codex: async (options) => {
        observed.push(String(options.schema)); return { message: "{}", stderr: "", ms: 1 };
      } });
    }
    assert.deepEqual(observed, ["producer-treatment-proposal", "producer-treatment-proposal-v3", "producer-treatment-proposal-v4"]);
  } finally {
    if (prior === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior;
  }
});
