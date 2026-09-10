/** TEST ONLY held-shaped metadata; not actual source, transcript, asset or admission observations. */
import { layoutOperation, layoutProposal, layoutSelection, type Row } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import { parseTreatmentProposalV8 } from "@/lib/producer/contracts/treatment-proposal-v8";
import { guidedPresenterPolicy, type GuidedPresenterFrameEvidence } from "../guided-proposal-presenter";
export { layoutOperation, layoutProposal, layoutSelection };
export type { Row };

export function presentationAsset(patch: Row = {}): Row {
  return { id: "presentation-1", originalPath: "/TEST-only/project/slide.png", path: "/TEST-only/admitted/slide.png",
    admissionReceiptPath: "/TEST-only/receipt.json", sourceSha256: "a".repeat(64), sourceSizeBytes: 4096,
    admissionReceiptSha256: "b".repeat(64), kind: "image", duration: null, resolution: [1920, 1080],
    licensed: true, descriptionSource: "TEST-only-unobserved", ...patch };
}

export function presenterProposal(operations?: Row[]) {
  const raw = layoutProposal({ operations: operations ?? [layoutOperation({ startAnchor: 2, endAnchorExclusive: 28 })] });
  (raw.beats as Row[])[0].endAnchorExclusive = 30;
  raw.openingEndAnchor = 30; raw.continuityEndAnchor = 30;
  (raw.clauses as Row[])[0].operationIndices = (raw.operations as Row[]).map((_, index) => index);
  return parseTreatmentProposalV8(raw);
}

export function presenterFixture() {
  const target = { mode: "longform", scope: "produced", lanes: {}, treatment: "produced", width: 1920, height: 1080, fps: 30 };
  const plan: Row = { planVersion: 2, target, cutTrack: [
    { sourceId: "raw-2", start: 5, end: 5 + 200 / 30 }, { sourceId: "raw-1", start: 1, end: 1 + 200 / 30 },
    { sourceId: "raw-2", start: 12, end: 12 + 200 / 30 }], cutDecisions: { schemaVersion: 1, removals: [] },
    captions: { burn: true }, captionsTrack: { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] },
    audioGain: [{ sourceId: "raw-2", gainDb: -1 }], unrelated: { exact: true } };
  const evidence: GuidedPresenterFrameEvidence = { target: structuredClone(target), frameRate: "30/1", totalFrames: 600,
    anchors: Array.from({ length: 31 }, (_, index) => index * 20), segments: [
      { index: 0, sourceId: "raw-2", startFrame: 0, endFrameExclusive: 200 },
      { index: 1, sourceId: "raw-1", startFrame: 200, endFrameExclusive: 400 },
      { index: 2, sourceId: "raw-2", startFrame: 400, endFrameExclusive: 600 }] };
  const manifest: Row = { sources: [{ id: "raw-2" }, { id: "raw-1" }], broll: [presentationAsset()] };
  return { plan, manifest, evidence, proposal: presenterProposal(), policy: guidedPresenterPolicy(plan, manifest) };
}
