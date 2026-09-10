import { readFileSync } from "node:fs";
import path from "node:path";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import { parseTreatmentProposalV5, type GuidedCaptionPreset, type TreatmentProposalV5 } from "@/lib/producer/contracts/treatment-proposal-v5";

/** TEST ONLY. A deterministic stand-in for the treatment brain: it maps the Python-authored, gate-validated
 * `test-treatment.json` copy onto the controller's exact frame anchors and cut seams. It makes no creative
 * judgement and is never a substitute for a real proposal or human review. */

interface TreatmentBeat { beatId: string; shape: string; outStart: number; kind: string; anchor: "own-screen" | "free-band";
  variables: Array<{ name: string; value: string | number | boolean }>;
  reason: string; selectionReason: string; alternativesConsidered: string[]; minimumHoldS: number; maximumHoldS: number }
interface Treatment { schemaVersion: 1; graphicsStyle: string; graphicsStyleRationale: string; beats: TreatmentBeat[];
  seamEvidence: Array<{ outTime: number; reason: string; evidence: string }> }
interface Evidence { schemaVersion: number; anchors: number[]; cleanEnds: number[]; frameRate: string; totalFrames: number;
  segments: Array<{ startFrame: number; endFrameExclusive: number }>; introSeams: Array<{ seamIndex: number; outTime: number; startFrame: number }>;
  catalog: Array<{ kind: string; defaults: Record<string, unknown>; fields: string[] }> }

const SEAM_TOL_S = 0.25;

export const TEST_CAPTION_INTENT = " Add captions for every kept transcript word using the captured Producer line preset.";

/** TEST ONLY: preserve every graphic/beat index and append one separately covered caption clause. */
export function appendTestCaptionProposal(proposal: Record<string, unknown> | TreatmentProposalV5, graphicsIntent: string, preset: GuidedCaptionPreset) {
  if (proposal.schemaVersion !== 5) throw new Error("TEST caption authoring requires the explicit V5 evidence/schema");
  if (preset !== "producer-config-line-v1") throw new Error("This longform TEST request declares only the line preset");
  const current = parseTreatmentProposalV5(proposal);
  if (current.clauses.length !== 1 || current.clauses[0].quote !== graphicsIntent) throw new Error("TEST graphics clause must retain its exact original intent");
  return parseTreatmentProposalV5({ ...current,
    clauses: [...current.clauses, { start: graphicsIntent.length, end: graphicsIntent.length + TEST_CAPTION_INTENT.length,
      quote: TEST_CAPTION_INTENT, disposition: "supported", rationale: "TEST ONLY all-kept source-bound line captions; no replacement speech.",
      operationIndices: [current.operations.length] }],
    operations: [...current.operations, { type: "captions-full-program", clauseIndex: 1, beatIndex: null, catalogKind: null,
      variables: null, grade: null, startAnchor: null, endAnchorExclusive: null, presentation: null,
      reason: "TEST ONLY exercises captured full-program captions through the same actual opening and body graph.",
      captions: { schemaVersion: 1, preset, coverage: "all-kept-transcript-words", suppression: "none" } }] });
}

function fps(evidence: Evidence): number { const [n, d] = evidence.frameRate.split("/").map(Number); return n / d; }
function seconds(frame: number, evidence: Evidence): number { return frame / fps(evidence); }

/** Hold-to-cut graphics end exactly on a cut seam (or the program end); choose the first seam past the minimum hold. */
function graphicAnchors(beat: TreatmentBeat, evidence: Evidence) {
  const rate = fps(evidence), startFrame = Math.floor(beat.outStart * rate);
  const startAnchor = evidence.anchors.reduce((best, frame, index) => frame <= startFrame ? index : best, 0);
  const seams = new Set(evidence.segments.slice(1).map((segment) => segment.startFrame)); seams.add(evidence.totalFrames);
  const minEnd = evidence.anchors[startAnchor] + Math.ceil(beat.minimumHoldS * rate), maxEnd = evidence.anchors[startAnchor] + Math.floor(beat.maximumHoldS * rate);
  const endAnchor = evidence.anchors.findIndex((frame, index) => index > startAnchor && seams.has(frame) && frame >= minEnd);
  if (endAnchor < 0 || evidence.anchors[endAnchor] > maxEnd) throw new Error(`TEST treatment: no cut seam within [${beat.minimumHoldS}, ${beat.maximumHoldS}]s after beat ${beat.beatId}`);
  return { startAnchor, endAnchorExclusive: endAnchor };
}

function openingBoundary(evidence: Evidence, ops: Array<{ startAnchor: number; endAnchorExclusive: number }>) {
  const rate = fps(evidence), busy = (index: number) => ops.some((op) => op.startAnchor < index && index < op.endAnchorExclusive);
  const clean = evidence.anchors.map((frame, index) => ({ frame, index })).filter(({ frame, index }) => evidence.cleanEnds.includes(frame)
    && seconds(frame, evidence) >= 60 && seconds(frame, evidence) <= 75 && !busy(index));
  if (!clean.length) throw new Error("TEST treatment: no clean opening endpoint within 60-75s outside a graphic window");
  const end = clean[0], contextFrom = end.frame + Math.ceil(5 * rate), contextTo = end.frame + Math.floor(15 * rate);
  const context = evidence.anchors.findIndex((frame) => frame >= contextFrom && frame <= contextTo);
  if (context < 0) throw new Error("TEST treatment: no continuity anchor 5-15s beyond the opening endpoint");
  return { openingEndAnchor: end.index, continuityEndAnchor: context };
}

export function longformProposal(input: ProposalBrainInput, rawIntent: string): Record<string, unknown> {
  const evidence = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]).evidence as Evidence;
  if (![4, 5].includes(evidence.schemaVersion)) throw new Error("TEST longform fixture needs explicit V4/V5 evidence");
  const treatment = JSON.parse(readFileSync(path.join(input.ctx.transcriptsDir, "test-treatment.json"), "utf8")) as Treatment;
  const ranges = treatment.beats.map((beat) => graphicAnchors(beat, evidence));
  const { openingEndAnchor, continuityEndAnchor } = openingBoundary(evidence, ranges);
  const last = evidence.anchors.length - 1;
  const beats = [{ startAnchor: 0, endAnchorExclusive: openingEndAnchor, purpose: "opening", summary: "TEST ONLY opening story beat over the authored program.", supportsBeatIndices: [] },
    { startAnchor: openingEndAnchor, endAnchorExclusive: last, purpose: "body", summary: "TEST ONLY body story beat to the program end.", supportsBeatIndices: [0] }];
  const beatIndexFor = (range: { startAnchor: number }) => range.startAnchor < openingEndAnchor ? 0 : 1;
  const operations = treatment.beats.map((beat, index) => {
    const catalog = evidence.catalog.find((row) => row.kind === beat.kind);
    if (!catalog) throw new Error(`TEST treatment: kind ${beat.kind} is not in the measured catalog`);
    const range = ranges[index];
    if (range.endAnchorExclusive > beats[beatIndexFor(range)].endAnchorExclusive) throw new Error(`TEST treatment: graphic ${beat.beatId} would straddle the opening/body boundary`);
    return { type: "catalog-graphic", clauseIndex: 0, beatIndex: beatIndexFor(range), catalogKind: beat.kind, variables: beat.variables, grade: null,
      startAnchor: range.startAnchor, endAnchorExclusive: range.endAnchorExclusive,
      presentation: beat.anchor === "own-screen"
        ? { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal", baseTreatment: "preserve",
          rationale: "TEST ONLY: own-screen full-canvas cutaway within the longform takeover budget." }
        : { schemaVersion: 1, anchor: "free-band", placement: "measured-free-region", compositeMode: "normal", baseTreatment: "preserve",
          rationale: "TEST ONLY: overlay card beside the presenter; the longform takeover cap leaves no own-screen budget for this beat." },
      reason: beat.reason, ...(evidence.schemaVersion === 5 ? { captions: null } : {}) };
  });
  const hookSeamDecisions = evidence.introSeams.map((seam) => {
    const row = treatment.seamEvidence.find((item) => Math.abs(item.outTime - seam.outTime) <= SEAM_TOL_S);
    if (!row) throw new Error(`TEST treatment: no seam evidence for intro seam at ${seam.outTime}s`);
    return { seamIndex: seam.seamIndex, decision: "clean-hook", reason: row.reason, evidence: row.evidence };
  });
  return { schemaVersion: evidence.schemaVersion, summary: "TEST ONLY deterministic treatment mapped onto exact anchors; no creative quality claim.",
    graphicsStyle: treatment.graphicsStyle, graphicsStyleRationale: treatment.graphicsStyleRationale,
    clauses: [{ start: 0, end: rawIntent.length, quote: rawIntent, disposition: "supported", rationale: "TEST ONLY: every authored beat receives one own-screen catalog graphic.", operationIndices: operations.map((_, index) => index) }],
    beats, operations,
    beatDecisions: treatment.beats.map((beat, index) => ({ beatId: beat.beatId, decision: "graphic", reason: beat.reason, kind: beat.kind,
      alternativesConsidered: beat.alternativesConsidered, selectionReason: beat.selectionReason, operationIndex: index })),
    hookSeamDecisions, openingEndAnchor, continuityEndAnchor, audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}
