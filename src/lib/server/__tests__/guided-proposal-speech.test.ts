import assert from "node:assert/strict";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { packetCutSegments, packetSpeechEvidence, type PacketSpeechEvidence } from "@/app/api/producer/auto-edit/plan-review-packet-source";
import { assertProposalAudioWindows, mapProposalOccurrences, proposalRelativeFrame, readProposalSourceSpeech } from "../guided-proposal-speech";
import { assertProposalAnchors, buildTreatmentCandidate } from "../guided-proposal-candidate";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import type { ProposalEvidence } from "../guided-proposal-evidence";

function speech(words: Array<{ word: string; start: number; end: number }>): PacketSpeechEvidence {
  return { missingTranscriptSourceIds: [], boundaryNeighbors: [], transcripts: [{ sourceId: "s", byteHash: "a".repeat(64),
    utteranceCount: 1, sourceWordCount: words.length, utterances: [{ start: 0, end: words.at(-1)!.end, text: "TEST source speech" }] }],
    keptWords: words.map((word) => ({ word: word.word, sourceId: "s", segmentIndex: 0, sourceStart: word.start,
      sourceEnd: word.end, sourceOriginalEnd: word.end, outputStart: word.start, outputEnd: word.end })) };
}
function program(words: Array<{ word: string; start: number; end: number }>, frameRate = "30/1") {
  const end = words.at(-1)!.end, totalFrames = proposalRelativeFrame({ time: end, origin: 0, frameRate, edge: "end" });
  const plan = { cutTrack: [{ sourceId: "s", start: 0, end }], cutDecisions: {} }, segments = packetCutSegments(plan);
  const partitions = [{ index: 0, sourceId: "s", startFrame: 0, endFrameExclusive: totalFrames, text: "TEST whole program" }];
  const mapped = mapProposalOccurrences({ segments, partitions, frameRate, totalFrames }, speech(words));
  const evidence = { schemaVersion: 2, frameRate, totalFrames, segments: partitions, ...mapped,
    catalog: [{ kind: "title-card", canvas: [1920, 1080], fields: ["title"], defaults: { title: "Example" } }], timelineMapHash: "c".repeat(64) } as unknown as ProposalEvidence;
  return { evidence, cut: { plan: { value: plan } } as unknown as AcceptedGuidedCut };
}
function fullProposal(evidence: ProposalEvidence) {
  const at = (seconds: number) => evidence.anchors.indexOf(proposalRelativeFrame({ time: seconds, origin: 0, frameRate: evidence.frameRate, edge: "end" }));
  return { schemaVersion: 2, summary: "TEST ONLY a ten-second creative intro reviewed within the first-minute context.",
    clauses: [{ start: 0, end: 9, quote: "Add title", disposition: "supported", rationale: "Exact title cue", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: at(10), purpose: "opening", summary: "Intro", supportsBeatIndices: [1] },
      { startAnchor: at(10), endAnchorExclusive: evidence.anchors.length - 1, purpose: "body", summary: "Payoff", supportsBeatIndices: [] }],
    operations: [{ type: "catalog-graphic", clauseIndex: 0, beatIndex: 0, catalogKind: "title-card", variables: [{ name: "title", value: "A meaningful cue" }],
      grade: null, startAnchor: at(1), endAnchorExclusive: at(2.5) }],
    openingEndAnchor: at(60), continuityEndAnchor: at(70), audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}

test("one continuous ten-minute cut permits a1.5s graphic and60s+10s review without changing picture cuts", () => {
  const words = Array.from({ length: 1200 }, (_, index) => ({ word: `w${index}${index % 10 === 9 ? "." : ""}`, start: index / 2, end: (index + 1) / 2 }));
  const { cut, evidence } = program(words), before = JSON.stringify(cut.plan.value);
  const result = buildTreatmentCandidate({ cut, evidence, rawIntent: "Add title", output: fullProposal(evidence) });
  assert.equal(result.blockers.length, 0); assert.equal(JSON.stringify(cut.plan.value), before);
  const graphic = (result.candidate!.graphicsTrack as Array<{ outStart: number; outEnd: number }>)[0];
  assert.equal(graphic.outStart, 1); assert.equal(graphic.outEnd, 2.5);
  assert.deepEqual(result.range!.approval, { startFrame: 0, endFrameExclusive: 1800 });
  assert.deepEqual(result.range!.review, { startFrame: 0, endFrameExclusive: 2100 });
  assert.equal(evidence.occurrences.length, 1200); assert.equal(result.range!.executable, false);
});

test("repeated payoff words map to every occurrence while the legacy first-match reader remains unchanged", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-occurrence-")));
  try {
    writeFileSync(path.join(directory, "s.json"), JSON.stringify({ transcript: [{ start: 0, end: 2, text: "Payoff repeats.",
      words: [{ word: "Payoff", start: 0, end: 1 }, { word: "repeats.", start: 1, end: 2 }] }] }));
    const ctx = { transcriptsDir: directory } as AcceptedGuidedCut["job"]["ctx"], manifest = { sources: [{ id: "s", duration: 2, transcriptPath: "s.json" }] };
    const segments = packetCutSegments({ cutTrack: [{ sourceId: "s", start: 0, end: 2 }, { sourceId: "s", start: 0, end: 2 }] });
    const legacy = packetSpeechEvidence(ctx, manifest, segments); assert.equal(legacy.keptWords.length, 2);
    const source = readProposalSourceSpeech(ctx, manifest, segments);
    const partitions = segments.map((segment) => ({ index: segment.index, sourceId: "s", startFrame: segment.index * 60, endFrameExclusive: (segment.index + 1) * 60, text: "" }));
    const result = mapProposalOccurrences({ segments, partitions, frameRate: "30/1", totalFrames: 120 }, source);
    assert.deepEqual(result.occurrences.map((word) => word.slice(0, 5)), [[0, 0, 0, 0, 30], [1, 0, 1, 30, 60], [2, 1, 0, 60, 90], [3, 1, 1, 90, 120]]);
    assert.equal(packetSpeechEvidence(ctx, manifest, segments).keptWords.length, 2);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("fractional FPS and words crossing trims use exact enclosure and explicit clip flags, never silent omission", () => {
  assert.equal(proposalRelativeFrame({ time: 0.3, origin: 0.1, frameRate: "30/1", edge: "start" }), 6);
  assert.equal(proposalRelativeFrame({ time: 0.3, origin: 0.1, frameRate: "30000/1001", edge: "start" }), 5);
  assert.equal(proposalRelativeFrame({ time: 0.3, origin: 0.1, frameRate: "30000/1001", edge: "end" }), 6);
  const segments = packetCutSegments({ cutTrack: [{ sourceId: "s", start: 0.5, end: 1.5 }] });
  const partitions = [{ index: 0, sourceId: "s", startFrame: 0, endFrameExclusive: 30, text: "" }];
  const result = mapProposalOccurrences({ segments, partitions, frameRate: "30000/1001", totalFrames: 30 },
    speech([{ word: "head", start: 0.2, end: 0.8 }, { word: "tail.", start: 1.2, end: 1.8 }]));
  assert.deepEqual(result.occurrences.map((word) => [word[3], word[4], word[6]]), [[0, 9, 1], [20, 30, 2]]);
  assert.deepEqual(result.cleanEnds, [], "a tail-clipped sentence is not a clean core endpoint");
});

test("J-cut or unknown lead windows block before transcript-only evidence can omit audible pre-in-point words", () => {
  assert.doesNotThrow(() => assertProposalAudioWindows([{ nextAudioLeadS: 0 }, { nextAudioLeadS: 0 }]));
  for (const nextAudioLeadS of [0.12, -0.12, null, undefined, "0", NaN]) {
    assert.throws(() => assertProposalAudioWindows([{ nextAudioLeadS: 0 }, { nextAudioLeadS }]), /temporarily unsupported.*replaced tails and pre-in-point speech/);
  }
});

test("punctuation under overlapping speech cannot create a clean endpoint; half-open adjacent words can", () => {
  const overlapping = program([{ word: "Done.", start: 0, end: 1 }, { word: "still speaking.", start: 0.5, end: 1.5 }]);
  assert.deepEqual(overlapping.evidence.cleanEnds, [45]);
  const adjacent = program([{ word: "Done.", start: 0, end: 1 }, { word: "Next.", start: 1, end: 1.5 }]);
  assert.deepEqual(adjacent.evidence.cleanEnds, [30, 45]);
});

test("no clean endpoint in a long utterance is a retained blocker; anchor collisions/reordering never become authority", () => {
  const { cut, evidence } = program(Array.from({ length: 1200 }, (_, index) => ({ word: `w${index}`, start: index / 2, end: (index + 1) / 2 })));
  const result = buildTreatmentCandidate({ cut, evidence, rawIntent: "Add title", output: fullProposal(evidence) });
  assert.equal(result.candidate, null); assert.match(result.blockers[0].reason, /clean endpoint/);
  for (const anchors of [[0, 0, 18000], [0, 20, 10, 18000], [1, 18000], [0, NaN, 18000]]) {
    assert.throws(() => assertProposalAnchors({ ...evidence, anchors }), /anchors/);
  }
  assert.throws(() => assertProposalAnchors({ ...evidence, cleanEnds: [23] }), /anchors/);
  const forged = fullProposal(evidence); forged.operations[0].endAnchorExclusive = evidence.anchors.length - 1;
  const clean = { ...evidence, cleanEnds: [1800] };
  assert.match(buildTreatmentCandidate({ cut, evidence: clean, rawIntent: "Add title", output: forged }).blockers[0].reason, /within its grounded beat/);
});
