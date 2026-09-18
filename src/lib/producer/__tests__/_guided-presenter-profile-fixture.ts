/** TEST ONLY declared metadata + actual pure candidate builder, not source admission or execution evidence. */
import assert from "node:assert/strict";
import { presenterFixture, presenterProposal, layoutOperation } from "@/lib/server/__tests__/_guided-proposal-presenter-fixture";
import { oldOperation, PRESENTER_RAW, type Row } from "./_presenter-layout-fixture";
import { buildTreatmentCandidate } from "@/lib/server/guided-proposal-candidate";
import { guidedPresenterPolicy } from "@/lib/server/guided-proposal-presenter";
import { guidedMusicPolicy } from "@/lib/server/guided-proposal-music";
import { guidedCaptionPolicy, GUIDED_CAPTION_CONFIG_FILES } from "@/lib/server/guided-proposal-captions";
import type { AcceptedGuidedCut } from "@/lib/server/guided-raw-treatment-store";
import type { ProposalEvidence } from "@/lib/server/guided-proposal-evidence";
import type { GuidedPresenterProfileInput } from "../contracts/guided-presenter-profile";
export { layoutOperation, oldOperation, presenterProposal };

export function profileGraphic(startAnchor = 0, endAnchorExclusive = 2): Row {
  return layoutOperation({ type: "catalog-graphic", presenterLayout: null, catalogKind: "TEST-card",
    variables: [{ name: "title", value: "TEST ONLY presentation" }], startAnchor, endAnchorExclusive,
    presentation: { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal",
      baseTreatment: "preserve", rationale: "TEST ONLY full-canvas native picture metadata." } });
}

export function materializeProfile(input: Omit<GuidedPresenterProfileInput, "candidate" | "bindings">): GuidedPresenterProfileInput {
  const target = input.accepted.target as Row;
  const cut = { plan: { value: input.accepted }, manifest: { value: input.manifest },
    job: { ctx: { intent: { ...target } } } } as unknown as AcceptedGuidedCut;
  const result = buildTreatmentCandidate({ cut, rawIntent: PRESENTER_RAW, output: input.proposal, evidence: input.evidence });
  assert.deepEqual(result.blockers, []); assert.ok(result.candidate); assert.ok(result.executionBindings);
  return { ...input, candidate: result.candidate, bindings: result.executionBindings };
}

export function presenterProfileFixture(options: { short?: boolean; captioned?: boolean; operations?: Row[] } = {}): GuidedPresenterProfileInput {
  const { short = false, captioned = true } = options, f = presenterFixture();
  delete f.plan.audioGain; delete f.plan.unrelated; delete f.plan.captionsTrack;
  f.plan.captions = { burn: false };
  if (short) {
    f.plan.target = { ...(f.plan.target as Row), mode: "short", width: 1080, height: 1920 };
    f.plan.cutTrack = [{ sourceId: "raw-1", start: 0, end: 20 }];
    f.evidence.segments = [{ index: 0, sourceId: "raw-1", startFrame: 0, endFrameExclusive: 600 }];
    // Inherited manual geometry qualifies only the renderer class, not fresh bootstrap crop authoring.
    if (!captioned) f.plan.reframe = { layout: "fill", crop: [0.5, 0, 0.5, 1], track: false };
  }
  f.evidence.target = structuredClone(f.plan.target as Row);
  const layout = { ...f.proposal.operations[0].presenterLayout!, ...(short ? { sourceIds: ["raw-1"] } : {}) };
  const operations = [...(captioned ? [oldOperation("captions-full-program")] : []),
    ...(short && captioned ? [oldOperation("reframe-manual-short")] : []),
    layoutOperation({ startAnchor: 2, endAnchorExclusive: 28, presenterLayout: layout })];
  const target = f.plan.target as Row;
  const evidence = { ...f.evidence, schemaVersion: 8, cleanEnds: [600], occurrences: [], timelineMapHash: "c".repeat(64),
    introSeams: [], hookWindowS: 60, graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [] } },
    catalog: [{ kind: "TEST-card", canvas: [target.width, target.height], defaults: { title: "TEST" }, fields: ["title"] }],
    captionPolicy: guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map(name => ({ name, sha256: "d".repeat(64) }))),
    musicPolicy: guidedMusicPolicy(f.plan, f.manifest), presenterPolicy: guidedPresenterPolicy(f.plan, f.manifest) } as unknown as ProposalEvidence;
  return materializeProfile({ accepted: f.plan, manifest: f.manifest, proposal: presenterProposal(options.operations ?? operations), evidence });
}
