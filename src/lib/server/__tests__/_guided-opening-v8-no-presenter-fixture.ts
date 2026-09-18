/** TEST-only controller-shaped metadata; no admission, provider, renderer or human approval. */
import { oldOperation, PRESENTER_RAW, type Row } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import { PROPOSAL_PRESENTATION_POLICY } from "@/lib/producer/contracts/treatment-proposal-v3";
import { presenterFixture, presenterProposal } from "./_guided-proposal-presenter-fixture";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { GUIDED_CAPTION_CONFIG_FILES, guidedCaptionPolicy } from "../guided-proposal-captions";
import { guidedPresenterPolicy } from "../guided-proposal-presenter";
import { guidedMusicPolicy } from "../guided-proposal-music";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import type { ReviewedProposalInput } from "../guided-proposal-review-packet";
import { parseCurrentTreatmentProposal } from "@/lib/producer/contracts/treatment-proposal-v8";
import { canonicalJsonSha256 } from "../auto-edit-hash";

export const TEST_HASH = "a".repeat(64);

/** TEST construction only; no actual packet is rewritten into a historical authority. */
export function historicalNoPresenterProposal(proposal: unknown, version: number) {
  const row = structuredClone(proposal) as Row;
  row.schemaVersion = version;
  if (version < 4) for (const key of ["graphicsStyle", "graphicsStyleRationale", "beatDecisions", "hookSeamDecisions"]) delete row[key];
  const operation = { ...oldOperation("preserve-cut") };
  for (const [key, introduced] of [["presenterLayout", 8], ["music", 7], ["reframe", 6], ["captions", 5], ["reason", 4], ["presentation", 3]] as const) {
    if (version < introduced) delete operation[key];
  }
  row.operations = [operation];
  return parseCurrentTreatmentProposal(row);
}

/** Author this in-memory TEST target before any projection; no held plan is retrofitted. */
export function noPresenterFixture(short = false, mixed = false) {
  const f = presenterFixture(), plan = structuredClone(f.plan), manifest = structuredClone(f.manifest);
  delete plan.audioGain; delete plan.unrelated; delete plan.captions; delete plan.captionsTrack;
  if (short) {
    plan.target = { ...(plan.target as Row), mode: "short", width: 1080, height: 1920 };
    plan.cutTrack = [{ sourceId: "raw-1", start: 0, end: 20 }];
    f.evidence.segments = [{ index: 0, sourceId: "raw-1", startFrame: 0, endFrameExclusive: 600 }];
  }
  if (mixed) {
    plan.target = { ...(plan.target as Row), music: true };
    manifest.music = [{ id: "music-1", path: "/TEST/snapshot.wav", originalPath: "/TEST/original.wav",
      sourceSha256: "e".repeat(64), sourceSizeBytes: 8000, admissionReceiptPath: "/TEST/receipt.json",
      admissionReceiptSha256: "f".repeat(64), duration: 5 }];
  }
  const operations = mixed ? [oldOperation("music-bed-full-program"), oldOperation("captions-full-program")]
    : [oldOperation("preserve-cut")];
  if (short) operations.push(oldOperation("reframe-manual-short"));
  const proposal = presenterProposal(operations), target = plan.target as Row;
  const evidence = { ...f.evidence, target, schemaVersion: 8, cleanEnds: [600], occurrences: [], catalog: [],
    timelineMapHash: TEST_HASH, introSeams: [], hookWindowS: 60, presentationPolicy: PROPOSAL_PRESENTATION_POLICY,
    graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [] } },
    captionPolicy: guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map(name => ({ name, sha256: TEST_HASH }))),
    musicPolicy: guidedMusicPolicy(plan, manifest), presenterPolicy: guidedPresenterPolicy(plan, manifest) } as unknown as ProposalEvidence;
  const cut = { plan: { value: plan }, manifest: { value: manifest },
    job: { ctx: { intent: { scope: target.scope, lanes: target.lanes, music: mixed } } } } as unknown as AcceptedGuidedCut;
  const result = buildTreatmentCandidate({ cut, evidence, output: proposal, rawIntent: PRESENTER_RAW });
  if (!result.candidate || result.blockers.length) throw new Error(`TEST fixture blocked: ${JSON.stringify(result.blockers)}`);
  const bindings = result.executionBindings!;
  const ready = { ...cut, result, evidence, proposalHash: TEST_HASH, clock: { hash: TEST_HASH },
    generationStartedAt: "2026-09-07T00:00:00.000Z", submission: { rawIntent: PRESENTER_RAW },
    pointer: { treatmentAdmissionHash: TEST_HASH, cutDecisionHash: TEST_HASH, pictureLockedRevisionHash: TEST_HASH } } as unknown as ReviewedProposalInput;
  const packet: Row = { proposal: result.proposal, evidence, candidate: result.candidate, executionBindings: bindings };
  return { plan, manifest, evidence, proposal: result.proposal, candidate: result.candidate, bindings, ready, packet,
    originalHash: canonicalJsonSha256({ plan, manifest, packet }) };
}
