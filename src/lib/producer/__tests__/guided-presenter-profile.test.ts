/** Metadata-only profile tests. No media, provider, source/rights or clearance approval. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { assertGuidedPresenterProfile, presenterOpeningProfile, presenterBodyProfile, isPresenterCaptionProfile,
  isPresenterManualProfile, PRESENTER_PROFILE, PRESENTER_SHORT_PROFILE, PRESENTER_CAPTION_PROFILE,
  PRESENTER_CAPTION_SHORT_PROFILE } from "../contracts/guided-presenter-profile";
import { openingMediaProfile, openingMediaProfileForPlan, assertManualShortPlan, assertManualCaptionShortPlan,
  assertManualShortGeometry } from "../contracts/guided-media-profile";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { guidedMusicPolicy } from "@/lib/server/guided-proposal-music";
import { guidedPresenterPolicy } from "@/lib/server/guided-proposal-presenter";
import { buildGuidedFrameBindings, type GuidedFrameBindingsV2 } from "@/lib/server/guided-proposal-bindings";
import { parseTreatmentProposalV8 } from "../contracts/treatment-proposal-v8";
import { layoutSelection, type Row } from "./_presenter-layout-fixture";
import { presenterProfileFixture, materializeProfile, presenterProposal, layoutOperation, oldOperation, profileGraphic } from "./_guided-presenter-profile-fixture";

test("four native presenter classes retain actual V8/cuts and do not release any legacy selector", () => {
  const cases = [[false, false, PRESENTER_PROFILE], [true, false, PRESENTER_SHORT_PROFILE],
    [false, true, PRESENTER_CAPTION_PROFILE], [true, true, PRESENTER_CAPTION_SHORT_PROFILE]] as const;
  for (const [short, captioned, profile] of cases) {
    const input = presenterProfileFixture({ short, captioned }), before = structuredClone(input);
    const result = assertGuidedPresenterProfile(input);
    assert.equal(result.profile, profile); assert.equal(result.bodyProfile, presenterBodyProfile(profile));
    assert.equal(presenterOpeningProfile(profile), profile); assert.equal(isPresenterCaptionProfile(profile), captioned);
    assert.equal(isPresenterManualProfile(profile), short); assert.equal(result.windows.length, 1);
    assert.equal(result.workload.captionPageCount, captioned ? 1 : 0); assert.deepEqual(input, before);
    assert.throws(() => openingMediaProfile(profile), /unsupported/);
    assert.throws(() => openingMediaProfileForPlan(input.candidate), /no presenterLayouts execution owner/);
  }
});

test("shared manual geometry is not a bypass of either historical public owner fence", () => {
  for (const captioned of [false, true]) {
    const input = presenterProfileFixture({ short: true, captioned });
    assertManualShortGeometry(input.candidate, captioned);
    const check = captioned ? assertManualCaptionShortPlan : assertManualShortPlan;
    assert.throws(() => check(input.candidate), /no presenterLayouts execution owner/);
    const bad = { ...input.candidate, reframe: { layout: "fill", track: false, crop: [0, 0, 0.049, 1] } };
    assert.throws(() => assertManualShortGeometry(bad, captioned), /normalized source bounds/);
  }
});

test("empty, inherited, downgraded or rehashed presenter authority cannot acquire the new class", () => {
  const input = presenterProfileFixture();
  for (const patch of [{ schemaVersion: 7 }, { presenterPolicy: undefined }]) {
    assert.throws(() => assertGuidedPresenterProfile({ ...input, evidence: { ...input.evidence, ...patch } as typeof input.evidence }));
  }
  for (const schemaVersion of [7, "8", true]) assert.throws(() => assertGuidedPresenterProfile({ ...input, proposal: { ...(input.proposal as Row), schemaVersion } }));
  const noop = materializeProfile({ ...input, proposal: presenterProposal([oldOperation("captions-full-program")]) });
  assert.throws(() => assertGuidedPresenterProfile(noop), /nonempty actual V8/);
  const binding = input.bindings as GuidedFrameBindingsV2;
  const candidate = { ...input.candidate, presenterLayouts: [{ ...binding.presenterLayouts[0], startFrame: 41 }] };
  assert.throws(() => assertGuidedPresenterProfile({ ...input, candidate, bindings: { ...binding,
    candidatePlanHash: canonicalJsonSha256(candidate), presenterLayouts: candidate.presenterLayouts } }), /actual V8/);
  assert.throws(() => assertGuidedPresenterProfile({ ...input, bindings: { ...binding, schemaVersion: 1 } }), /bindings changed/);
});

test("unchanged or exact paired graphic-style decoration is accepted; altered target is never a crop authority", () => {
  const input = presenterProfileFixture();
  assertGuidedPresenterProfile(input);
  const candidate = { ...input.candidate, target: structuredClone(input.accepted.target) };
  const bindings = buildGuidedFrameBindings({ proposal: parseTreatmentProposalV8(input.proposal), candidate, evidence: input.evidence, inheritedCount: 0 });
  assertGuidedPresenterProfile({ ...input, candidate, bindings });
  for (const patch of [{ width: 1080 }, { scope: "full" }, { lanes: { motion: "off" } }, { arbitrary: 1 },
    { graphicsStyleRationale: "Different reason" }]) {
    const target = { ...(input.candidate.target as Row), ...patch };
    assert.throws(() => assertGuidedPresenterProfile({ ...input, candidate: { ...input.candidate, target } }), /Candidate target differs/);
  }
});

test("explicit no-caption choice and unchanged supported preset never ignore a track or custom authority", () => {
  const input = presenterProfileFixture({ captioned: false });
  for (const captions of [undefined, {}, { burn: 0 }, { burn: false, ignored: true }]) {
    assert.throws(() => assertGuidedPresenterProfile({ ...input, accepted: { ...input.accepted, captions }, candidate: { ...input.candidate, captions } }));
  }
  for (const captionsTrack of [[], null, undefined]) {
    const accepted = { ...input.accepted, captionsTrack }, candidate = { ...input.candidate, captionsTrack };
    assert.throws(() => assertGuidedPresenterProfile({ ...input, accepted, candidate }), /absent captionsTrack|outside the JSON domain/);
  }
  const captioned = presenterProfileFixture();
  for (const key of ["captionChapters", "captionStyles", "captionCorrectionLedger", "dialogueCaptionAuthority"]) {
    assert.throws(() => assertGuidedPresenterProfile({ ...captioned, candidate: { ...captioned.candidate, [key]: [] } }));
  }
});

test("unsupported lanes, J-cut/bool speed, invented crop and numeric metadata still refuse", () => {
  const input = presenterProfileFixture();
  for (const key of ["titleCards", "brollTrack", "baselineLook", "punchIns", "transitions", "audioEnhance", "audioGain", "persistentText"]) {
    assert.throws(() => assertGuidedPresenterProfile({ ...input, candidate: { ...input.candidate, [key]: [{ active: true }] } }), /unqualified/);
  }
  for (const patch of [{ speed: true }, { speed: 1.01 }, { audioLeadMs: false }, { audioLeadMs: 1 }]) {
    const cutTrack = (input.accepted.cutTrack as Row[]).map(row => ({ ...row, ...patch }));
    assert.throws(() => assertGuidedPresenterProfile({ ...input, accepted: { ...input.accepted, cutTrack }, candidate: { ...input.candidate, cutTrack } }));
  }
  const short = presenterProfileFixture({ short: true });
  assert.throws(() => assertGuidedPresenterProfile({ ...short, candidate: { ...short.candidate,
    reframe: { layout: "fill", track: false, crop: [0, 0, 1, 1] } } }), /actual V6 request/);
});

test("full-program graphics are allowed only disjoint; exact adjacent endpoints preserve original array indices", () => {
  const operations = [profileGraphic(28, 30), oldOperation("captions-full-program"),
    layoutOperation({ startAnchor: 2, endAnchorExclusive: 28 }), profileGraphic(0, 2)];
  const input = presenterProfileFixture({ operations });
  const result = assertGuidedPresenterProfile(input); assert.equal(result.windows[0].operationIndex, 2);
  assert.equal(result.workload.graphicCount, 2);
  for (const [start, end] of [[0, 3], [27, 30], [2, 28], [5, 6]]) {
    const overlap = presenterProfileFixture({ operations: [oldOperation("captions-full-program"),
      layoutOperation({ startAnchor: 2, endAnchorExclusive: 28 }), profileGraphic(start, end)] });
    assert.throws(() => assertGuidedPresenterProfile(overlap), /must not overlap/);
  }
});

test("inset, bubble and split share declared geometry while upscaling and nonnormal graphics stay refused", () => {
  for (const kind of ["inset", "bubble", "split"] as const) {
    const input = presenterProfileFixture({ operations: [oldOperation("captions-full-program"),
      layoutOperation({ startAnchor: 2, endAnchorExclusive: 28, presenterLayout: layoutSelection(kind) })] });
    assert.equal(assertGuidedPresenterProfile(input).windows[0].layout.layout, kind);
  }
  const layout = layoutSelection(); layout.presenterCrop = { x: 0.25, y: 0.25, width: 0.5, height: 0.5 };
  layout.protectedPresenterRect = { x: 0.4, y: 0.4, width: 0.2, height: 0.2 };
  layout.presenterRect = { x: 0, y: 0, width: 0.75, height: 0.75 };
  const upscale = presenterProfileFixture({ operations: [oldOperation("captions-full-program"),
    layoutOperation({ startAnchor: 2, endAnchorExclusive: 28, presenterLayout: layout })] });
  assert.throws(() => assertGuidedPresenterProfile(upscale), /upscaling/);
  const input = presenterProfileFixture({ operations: [profileGraphic(), oldOperation("captions-full-program"),
    layoutOperation({ startAnchor: 2, endAnchorExclusive: 28 })] });
  const candidate = structuredClone(input.candidate); (candidate.graphicsTrack as Row[])[0].exitOnCut = true;
  const bindings = buildGuidedFrameBindings({ candidate, proposal: parseTreatmentProposalV8(input.proposal), evidence: input.evidence, inheritedCount: 0 });
  assert.throws(() => assertGuidedPresenterProfile({ ...input, candidate, bindings }), /without holes or added placement/);
});

test("mixed requested music and captions retain exact policies; a changed admitted asset cannot inherit old evidence", () => {
  const original = presenterProfileFixture(), accepted = { ...original.accepted, target: { ...(original.accepted.target as Row), music: true } };
  const manifest = { ...original.manifest, music: [{ id: "music-1", path: "/TEST/snapshot.wav", originalPath: "/TEST/original.wav",
    sourceSha256: "e".repeat(64), sourceSizeBytes: 8000, admissionReceiptPath: "/TEST/receipt.json", admissionReceiptSha256: "f".repeat(64), duration: 5 }] };
  const evidence = { ...original.evidence, target: accepted.target, musicPolicy: guidedMusicPolicy(accepted, manifest),
    presenterPolicy: guidedPresenterPolicy(accepted, manifest) };
  const input = materializeProfile({ accepted, manifest, evidence, proposal: presenterProposal([oldOperation("music-bed-full-program"),
    oldOperation("captions-full-program"), layoutOperation({ startAnchor: 2, endAnchorExclusive: 28 })]) });
  const before = structuredClone(input); assertGuidedPresenterProfile(input); assert.deepEqual(input, before);
  assert.equal((input.candidate.music as Row).assetId, "music-1");
  const broll = structuredClone(input.manifest.broll) as Row[]; broll[0].resolution = [1280, 720];
  assert.throws(() => assertGuidedPresenterProfile({ ...input, manifest: { ...input.manifest, broll } }), /Presenter policy differs/);
  assert.throws(() => assertGuidedPresenterProfile({ ...input, evidence: { ...evidence, captionPolicy: undefined } }), /caption policy/);
  assert.throws(() => assertGuidedPresenterProfile({ ...input, candidate: { ...input.candidate, music: { ...(input.candidate.music as Row), gapDb: 12 } } }), /prior lanes/);
});

test("graphics entirely after the opening review still cannot overlap a requested presenter", () => {
  const original = presenterProfileFixture(), cutTrack = (original.accepted.cutTrack as Row[]).map(row => ({ ...row, end: Number(row.start) + 40 }));
  const accepted = { ...original.accepted, cutTrack };
  const evidence = { ...original.evidence, totalFrames: 3600, anchors: Array.from({ length: 31 }, (_, i) => i * 120), cleanEnds: [2160, 3600],
    segments: original.evidence.segments.map((row, index) => ({ ...row, startFrame: index * 1200, endFrameExclusive: (index + 1) * 1200 })) };
  const layout = { ...layoutSelection(), sourceIds: ["raw-2"] };
  const proposal = { ...presenterProposal([oldOperation("captions-full-program"),
    layoutOperation({ startAnchor: 22, endAnchorExclusive: 28, presenterLayout: layout }), profileGraphic(25, 27)]),
    openingEndAnchor: 18, continuityEndAnchor: 20 };
  const input = materializeProfile({ accepted, manifest: original.manifest, evidence, proposal });
  assert.ok((input.bindings as GuidedFrameBindingsV2).graphics[0].startFrame > evidence.anchors[20]);
  assert.throws(() => assertGuidedPresenterProfile(input), /must not overlap/);
});

test("new longform class refuses falsey malformed reframe without altering the legacy truthiness policy", () => {
  const original = presenterProfileFixture();
  for (const reframe of [false, 0, "", []]) {
    const input = materializeProfile({ ...original, accepted: { ...original.accepted, reframe } });
    assert.throws(() => assertGuidedPresenterProfile(input), /presenter longform reframe/);
  }
  for (const reframe of [null, {}, { strategy: "none" }]) {
    const input = materializeProfile({ ...original, accepted: { ...original.accepted, reframe } });
    assertGuidedPresenterProfile(input);
  }
});
