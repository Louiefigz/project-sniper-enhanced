import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { parseRawTreatmentSubmissionV1, parseTreatmentCompileSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { parseTreatmentProposalV2, assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { buildProposalPrompt, runProposalBrain } from "../guided-proposal-compiler";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import { selectProposalCatalog } from "../guided-proposal-evidence";
import { assertProposalUsedSpeech } from "../guided-proposal-speech";
import { packetCutSegments, type PacketSpeechEvidence } from "@/app/api/producer/auto-edit/plan-review-packet-source";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";

const request = { schemaVersion: 1, operation: "propose-post-cut-treatment", requestId: randomUUID(), idempotencyKey: randomUUID(),
  expectedToken: "token", expectedJournalHash: "a".repeat(64), cutDecisionHash: "b".repeat(64), parentRevisionHash: "c".repeat(64), rawIntent: "Keep 😀" };
function proposal(raw = request.rawIntent) {
  return { schemaVersion: 2, summary: "TEST ONLY proposal", clauses: [{ start: 0, end: raw.length, quote: raw,
    disposition: "supported", rationale: "Keep accepted cut", operationIndices: [0] }],
  beats: [{ startAnchor: 0, endAnchorExclusive: 3, purpose: "opening", summary: "Opening promise", supportsBeatIndices: [1] },
    { startAnchor: 3, endAnchorExclusive: 6, purpose: "body", summary: "Body payoff", supportsBeatIndices: [] }],
  operations: [{ type: "preserve-cut", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null, grade: null, startAnchor: null, endAnchorExclusive: null }],
  openingEndAnchor: 3, continuityEndAnchor: 4, audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}
const evidence = { schemaVersion: 2, segments: [{ index: 0, sourceId: "s", startFrame: 0, endFrameExclusive: 1800, text: "Promise" },
  { index: 1, sourceId: "s", startFrame: 1800, endFrameExclusive: 18000, text: "Payoff" }], frameRate: "30/1", totalFrames: 18000,
  target: { mode: "longform", width: 1920, height: 1080 },
  timelineMapHash: "e".repeat(64), catalog: [{ kind: "title-card", canvas: [1920, 1080], defaults: { title: "Example" }, fields: ["title"] }],
  anchors: [0, 30, 60, 1800, 1950, 2100, 18000], cleanEnds: [1800],
} as unknown as ProposalEvidence;
const cut = { plan: { value: { cutTrack: [{ sourceId: "s", start: 0, end: 600 }], cutDecisions: {} } } } as unknown as AcceptedGuidedCut;

test("raw and retry requests are closed, bounded and contain no implicit attestation", () => {
  assert.deepEqual(parseRawTreatmentSubmissionV1(request), request);
  for (const patch of [{ rawIntent: " " }, { rawIntent: "😀".repeat(10001) }, { attestation: true }, { requestId: "../unsafe" }]) {
    assert.throws(() => parseRawTreatmentSubmissionV1({ ...request, ...patch }));
  }
  assert.throws(() => parseTreatmentCompileSubmissionV1({ ...request, operation: "compile-post-cut-proposal" }));
});

test("one available transcript cannot mask another used source's missing or empty speech", () => {
  const segments = packetCutSegments({ cutTrack: [{ sourceId: "a", start: 0, end: 2 }, { sourceId: "b", start: 0, end: 2 }] });
  const speech = { keptWords: [{ sourceId: "a" }], transcripts: [{ sourceId: "a", sourceWordCount: 1 }],
    missingTranscriptSourceIds: ["b"], boundaryNeighbors: [] } as unknown as PacketSpeechEvidence;
  assert.throws(() => assertProposalUsedSpeech(segments, speech), /every used source/);
  speech.missingTranscriptSourceIds = []; speech.transcripts.push({ sourceId: "b", sourceWordCount: 0 } as PacketSpeechEvidence["transcripts"][number]);
  assert.throws(() => assertProposalUsedSpeech(segments, speech), /every used source/);
  assert.doesNotThrow(() => assertProposalUsedSpeech(segments.slice(0, 1), { ...speech, missingTranscriptSourceIds: ["unused-silent"] }));
});

test("mode-only destinations and malformed catalog canvases cannot admit both portrait and landscape", () => {
  const row = { canvas: [1920, 1080], specFields: ["title"], specDefaults: { title: "sample" } };
  const rows = { landscape: row, portrait: { ...row, canvas: [1080, 1920] } };
  assert.throws(() => selectProposalCatalog(rows, { mode: "longform" }), /exact bounded destination/);
  assert.deepEqual(selectProposalCatalog(rows, { width: 1920, height: 1080 }).map((item) => item.kind), ["landscape"]);
  assert.deepEqual(selectProposalCatalog(rows, { width: 1080, height: 1920 }).map((item) => item.kind), ["portrait"]);
  for (const dimensions of [[0, 1080], ["1920", 1080], [NaN, 1080], [1920], [1920, 1080, 30]]) {
    assert.throws(() => selectProposalCatalog({ malformed: { ...row, canvas: dimensions } }, { width: 1920, height: 1080 }), /malformed measured/);
  }
});

test("grade-only intent remains blocked and cannot materialize default zoom/crop/output size", () => {
  const output = proposal() as unknown as Record<string, unknown>;
  output.operations = [{ type: "grade", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null, grade: "warm", startAnchor: null, endAnchorExclusive: null }]; output.colorPolicy = "warm";
  const result = buildTreatmentCandidate({ cut, evidence, rawIntent: request.rawIntent, output });
  assert.equal(result.candidate, null); assert.match(result.blockers[0].reason, /source-aware color\/profile/);
  assert.equal(cut.plan.value.baselineLook, undefined);
});

test("clause partition cannot omit prose, split Unicode, duplicate references or hide a blocked operation", () => {
  assertProposalClauseCoverage(parseTreatmentProposalV2(proposal()), request.rawIntent);
  const bad = proposal(); bad.clauses[0].end -= 1;
  assert.throws(() => assertProposalClauseCoverage(parseTreatmentProposalV2(bad), request.rawIntent));
  const split = proposal(); split.clauses = [{ ...split.clauses[0], end: 6, quote: "Keep \uD83D" },
    { ...split.clauses[0], start: 6, quote: "\uDE00", disposition: "ambiguous", operationIndices: [] }];
  assert.throws(() => assertProposalClauseCoverage(parseTreatmentProposalV2(split), request.rawIntent), /Unicode/);
  const blocked = proposal(); blocked.clauses[0].disposition = "unsupported";
  assert.throws(() => assertProposalClauseCoverage(parseTreatmentProposalV2(blocked), request.rawIntent), /blocked/);
  assert.throws(() => parseTreatmentProposalV2({ ...proposal(), finalApproved: true }));
});

test("proposal covers all speech and derives opening plus actual body context without approving playback", () => {
  assert.throws(() => buildTreatmentCandidate({ cut, evidence: { ...evidence, schemaVersion: 3 }, rawIntent: request.rawIntent,
    output: proposal() }), /exact versioned evidence/);
  const result = buildTreatmentCandidate({ cut, evidence, rawIntent: request.rawIntent, output: proposal() });
  assert.deepEqual(result.range!.approval, { startFrame: 0, endFrameExclusive: 1800 });
  assert.deepEqual(result.range!.review, { startFrame: 0, endFrameExclusive: 1950 });
  assert.equal(result.range!.executable, false); assert.deepEqual(result.candidate!.cutTrack, cut.plan.value.cutTrack);
  assert.match(buildTreatmentCandidate({ cut, evidence, rawIntent: request.rawIntent, output: { ...proposal(), continuityEndAnchor: 3 } }).blockers[0].reason, /continuity/);
  const gaps = proposal(); gaps.beats[1].startAnchor = 2;
  assert.throws(() => buildTreatmentCandidate({ cut, evidence, rawIntent: request.rawIntent, output: gaps }), /complete program/);
  const graphics = proposal() as unknown as Record<string, unknown>;
  graphics.operations = [{ type: "catalog-graphic", clauseIndex: 0, beatIndex: 0, catalogKind: "invented", variables: [{ name: "title", value: "Claim" }], grade: null, startAnchor: 1, endAnchorExclusive: 2 }];
  const blocked = buildTreatmentCandidate({ cut, evidence, rawIntent: request.rawIntent, output: graphics });
  assert.equal(blocked.candidate, null); assert.match(blocked.blockers[0].reason, /unavailable/);
});

test("configured compiler remains sessionless/read-only/tools-none with unchanged effort and strict response bounds", async () => {
  const prior = { provider: process.env.SNIPER_BRAIN_PROVIDER, effort: process.env.SNIPER_CODEX_REASONING };
  try {
    process.env.SNIPER_BRAIN_PROVIDER = "codex"; process.env.SNIPER_CODEX_REASONING = "ultra";
    const input = { prompt: "TEST ONLY", ctx: {} as AcceptedGuidedCut["job"]["ctx"], cwd: "/private/tmp", timeoutMs: 500,
      schema: { properties: { schemaVersion: { const: 2 } } } };
    await assert.rejects(runProposalBrain({ ...input, schema: {} }), /Unsupported captured proposal schema/);
    const result = await runProposalBrain(input, { codex: async (options) => {
      assert.equal(options.reasoning, "ultra"); assert.equal(options.tools, "none"); assert.equal(options.sandbox, "read-only");
      assert.equal(options.schema, "producer-treatment-proposal"); assert.equal(options.maxOutputBytes, 1048576);
      return { message: "{}", stderr: "", ms: 1 };
    }, legacy: async () => { throw new Error("wrong provider"); } });
    assert.equal(result.effort, "ultra");
    await assert.rejects(runProposalBrain(input, { codex: async () => ({ message: "{", stderr: "", ms: 1 }) }), /JSON/);
    await assert.rejects(runProposalBrain(input, { codex: async () => ({ message: "a".repeat(1048577), stderr: "", ms: 1 }) }), /exceeds/);
    assert.throws(() => buildProposalPrompt("a".repeat(600000), evidence), /no silent truncation/);
    process.env.SNIPER_BRAIN_PROVIDER = "legacy";
    await runProposalBrain(input, { legacy: async (options) => {
      assert.equal(options.args[options.args.indexOf("--tools") + 1], ""); assert.equal(options.args.includes("--resume"), false);
      assert.equal(options.args[options.args.indexOf("--effort") + 1], "xhigh"); assert.equal(options.maxOutputBytes, 1048576);
      return { message: "{}", stderr: "", ms: 1 };
    } });
  } finally {
    if (prior.provider === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior.provider;
    if (prior.effort === undefined) delete process.env.SNIPER_CODEX_REASONING; else process.env.SNIPER_CODEX_REASONING = prior.effort;
  }
});
