import assert from "node:assert/strict";
import { test } from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { applyGuidedPresenterOperations, assertGuidedPresenterCandidate, assertGuidedPresenterIntent, guidedPresenterPolicy,
  guidedPresenterWindows } from "../guided-proposal-presenter";
import { oldOperation } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import { presenterFixture, presenterProposal, presentationAsset, layoutOperation, layoutSelection, type Row } from "./_guided-proposal-presenter-fixture";

test("presenter policy retains complete ordered admission metadata without paths or rights approval", () => {
  const f = presenterFixture(), video = presentationAsset({ id: "video-1", kind: "video", duration: 60, resolution: [1080, 1920] });
  const before = structuredClone(f.manifest); (f.manifest.broll as Row[]).push(video);
  const policy = guidedPresenterPolicy(f.plan, f.manifest);
  assert.equal(policy.scope, "admitted-project-presentation-metadata-not-source-rights-or-quality-approval");
  assert.equal(policy.acceptedMotionEnabled, true); assert.equal(policy.acceptedBrollEnabled, true);
  assert.deepEqual(policy.assets.map(row => [row.assetId, row.kind, row.durationS, row.rights]),
    [["presentation-1", "image", null, "unverified"], ["video-1", "video", 60, "unverified"]]);
  assert.equal(JSON.stringify(policy).includes("/TEST-only"), false);
  assert.deepEqual(f.manifest, { ...before, broll: [...before.broll as Row[], video] });
  assert.deepEqual(Object.keys(policy.assets[0]).sort(), ["assetId", "sourceSha256", "sourceSizeBytes", "admissionReceiptSha256",
    "kind", "durationS", "width", "height", "rights"].sort());
});

test("every broll row needs complete bounded metadata, without excluding an invalid unselected row", () => {
  const f = presenterFixture();
  const faults = [{ originalPath: undefined }, { path: " " }, { admissionReceiptPath: null }, { sourceSha256: "bad" },
    { admissionReceiptSha256: "B".repeat(64) }, { sourceSizeBytes: true }, { sourceSizeBytes: 0 }, { sourceSizeBytes: Number.MAX_SAFE_INTEGER + 1 },
    { kind: "audio" }, { kind: ["image"] }, { duration: 0 }, { duration: undefined }, { resolution: [1920] },
    { resolution: [true, 1080] }, { resolution: [0, 1080] }, { resolution: [16385, 1080] }, { id: " " }];
  for (const patch of faults) assert.throws(() => guidedPresenterPolicy(f.plan, { broll: [presentationAsset(), presentationAsset({ id: "other", ...patch })] }));
  for (const duration of [null, 0, -1, true, "60", NaN, Infinity]) {
    assert.throws(() => guidedPresenterPolicy(f.plan, { broll: [presentationAsset({ kind: "video", duration })] }));
  }
  for (const broll of [null, {}, [presentationAsset(), presentationAsset()], Array(129).fill(presentationAsset())]) {
    assert.throws(() => guidedPresenterPolicy(f.plan, { broll }));
  }
});

test("motion and broll resolve from exact accepted scope and explicit directives", () => {
  const f = presenterFixture();
  for (const scope of ["trim", "light", "produced", "full"]) {
    const policy = guidedPresenterPolicy({ target: { scope, lanes: { motion: "auto", broll: "auto" } } }, f.manifest);
    assert.equal(policy.acceptedMotionEnabled, scope !== "trim");
    assert.equal(policy.acceptedBrollEnabled, scope === "produced" || scope === "full");
  }
  for (const directive of ["off", "operator"]) {
    const policy = guidedPresenterPolicy({ target: { scope: "produced", lanes: { motion: directive, broll: directive } } }, f.manifest);
    assert.equal(policy.acceptedMotionEnabled || policy.acceptedBrollEnabled, false);
  }
  for (const target of [{}, { scope: "guess" }, { scope: "produced", lanes: { broll: ["presentation-1"] } },
    { scope: "produced", lanes: { broll: true } }, { scope: "produced", lanes: { typo: "auto" } }]) {
    assert.throws(() => guidedPresenterPolicy({ target }, f.manifest));
  }
});

test("target scope and actual operator override maps cannot substitute equal resolved permissions", () => {
  const f = presenterFixture(); assertGuidedPresenterIntent(f.plan, { scope: "produced", lanes: {} });
  assertGuidedPresenterIntent(f.plan, { scope: "produced" });
  for (const intent of [{ scope: "full", lanes: {} }, { scope: "produced", lanes: { motion: "auto" } },
    { scope: "produced", lanes: { broll: "off" } }, { scope: "produced", lanes: { motion: true } }, null]) {
    assert.throws(() => assertGuidedPresenterIntent(f.plan, intent));
  }
});

test("projection adds only actual windows, preserving all cuts, captions, target, audio and supplied objects", () => {
  const f = presenterFixture(), before = structuredClone(f), candidate = applyGuidedPresenterOperations(f);
  const { presenterLayouts, ...unchanged } = candidate;
  assert.deepEqual(unchanged, before.plan); assert.deepEqual(f, before);
  assert.deepEqual(presenterLayouts, [{ operationIndex: 0, startFrame: 40, endFrameExclusive: 560, layout: f.proposal.operations[0].presenterLayout }]);
  assertGuidedPresenterCandidate({ accepted: f.plan, candidate, manifest: f.manifest, proposal: f.proposal, evidence: f.evidence });
  (candidate.target as Row).width = 1;
  assert.equal((f.plan.target as Row).width, 1920);
});

test("an exact policy cannot be replaced by a rehashed metadata subset or invented approval", () => {
  const f = presenterFixture();
  for (const patch of [{ assets: [] }, { acceptedBrollEnabled: false }, { scope: "approved" }, { extra: undefined }]) {
    assert.throws(() => applyGuidedPresenterOperations({ ...f, policy: { ...f.policy, ...patch } as typeof f.policy }));
  }
  for (const patch of [{ sourceSha256: "c".repeat(64) }, { rights: "approved" }, { width: 1080 }, { path: undefined }]) {
    const changed = structuredClone(f); Object.assign(changed.policy.assets[0], patch);
    assert.throws(() => applyGuidedPresenterOperations(changed));
  }
  const changed = structuredClone(f); (changed.manifest.broll as Row[])[0].sourceSha256 = "d".repeat(64);
  assert.throws(() => applyGuidedPresenterOperations(changed), /policy differs/);
});

test("new windows refuse off lanes, inherited layout roots, unknown assets and nonzero image offsets", () => {
  const f = presenterFixture();
  for (const key of ["presenterLayouts", "presenter", "overlays"]) {
    for (const value of [null, [], {}]) assert.throws(() => applyGuidedPresenterOperations({ ...f, plan: { ...f.plan, [key]: value } }), /inherited/);
  }
  for (const scope of ["trim", "light"]) {
    const plan = { ...f.plan, target: { ...f.plan.target as Row, scope } };
    assert.throws(() => applyGuidedPresenterOperations({ ...f, plan, policy: guidedPresenterPolicy(plan, f.manifest) }), /motion\/broll/);
  }
  const unknown = structuredClone(f); unknown.proposal.operations[0].presenterLayout!.assetId = "/tmp/guess.mp4";
  assert.throws(() => applyGuidedPresenterOperations(unknown), /not in the exact/);
  const offset = structuredClone(f); offset.proposal.operations[0].presenterLayout!.assetStart = { numerator: 1, denominator: 30 };
  assert.throws(() => applyGuidedPresenterOperations(offset), /still image/);
});

test("video offsets remain authored metadata, not a claim of decoded or aligned executable clock", () => {
  const f = presenterFixture(); (f.manifest.broll as Row[])[0] = presentationAsset({ kind: "video", duration: 60 });
  f.policy = guidedPresenterPolicy(f.plan, f.manifest); f.proposal.operations[0].presenterLayout!.assetStart = { numerator: 1, denominator: 7 };
  const candidate = applyGuidedPresenterOperations(f);
  assert.deepEqual((candidate.presenterLayouts as Row[])[0].layout, f.proposal.operations[0].presenterLayout);
  assert.equal(JSON.stringify(candidate).includes("executable"), false);
});

test("no layout operations preserve inherited roots exactly, without manufacturing frames", () => {
  const f = presenterFixture(), plan = { ...f.plan, presenterLayouts: [{ inherited: true }], presenter: null, overlays: [] };
  const proposal = presenterProposal([oldOperation("preserve-cut")]);
  assert.deepEqual(guidedPresenterWindows(proposal, {} as typeof f.evidence), []);
  const candidate = applyGuidedPresenterOperations({ ...f, plan, proposal });
  assert.deepEqual(candidate, plan); assert.notEqual(candidate, plan);
  assertGuidedPresenterCandidate({ accepted: plan, candidate, manifest: f.manifest, proposal, evidence: f.evidence });
});

test("candidate rederivation rejects changed windows, cut, target and added legacy authority despite fresh hashes", () => {
  const f = presenterFixture(), original = applyGuidedPresenterOperations(f);
  const faults = [structuredClone(original), structuredClone(original), structuredClone(original), structuredClone(original)];
  (faults[0].presenterLayouts as Row[])[0].startFrame = 41;
  (faults[1].cutTrack as Row[])[0].start = 6;
  (faults[2].target as Row).scope = "full";
  faults[3].presenter = {};
  for (const candidate of faults) {
    assert.notEqual(canonicalJsonSha256(candidate), canonicalJsonSha256(original));
    assert.throws(() => assertGuidedPresenterCandidate({ accepted: f.plan, candidate, manifest: f.manifest, proposal: f.proposal, evidence: f.evidence }), /differs/);
  }
});

test("accepted cut source/count/speed and complete target must match independently held evidence", () => {
  const f = presenterFixture();
  for (const patch of [{ sourceId: "other" }, { speed: 2 }]) {
    const plan = structuredClone(f.plan); Object.assign((plan.cutTrack as Row[])[0], patch);
    assert.throws(() => applyGuidedPresenterOperations({ ...f, plan }), /accepted speed-1/);
  }
  const plan = structuredClone(f.plan); (plan.cutTrack as Row[]).pop();
  assert.throws(() => applyGuidedPresenterOperations({ ...f, plan }), /segment coverage/);
  const evidence = structuredClone(f.evidence); evidence.target.fps = 24;
  assert.throws(() => applyGuidedPresenterOperations({ ...f, evidence }), /evidence target/);
});

test("original operation indices survive chronological sorting among unrelated V8 operations", () => {
  const f = presenterFixture(), selection = { ...layoutSelection(), sourceIds: ["raw-2"] };
  const proposal = presenterProposal([layoutOperation({ startAnchor: 21, endAnchorExclusive: 28, presenterLayout: selection }),
    oldOperation("captions-full-program"), layoutOperation({ startAnchor: 2, endAnchorExclusive: 8, presenterLayout: selection })]);
  assert.deepEqual(guidedPresenterWindows(proposal, f.evidence).map(row => row.operationIndex), [2, 0]);
  assert.equal(proposal.operations[0].startAnchor, 21); assert.equal(proposal.operations[2].startAnchor, 2);
});

test("candidate target accepts only unchanged target or both exact actual-proposal graphics-style decorations", () => {
  const f = presenterFixture(), plain = applyGuidedPresenterOperations(f);
  const decorate = { graphicsStyle: f.proposal.graphicsStyle, graphicsStyleRationale: f.proposal.graphicsStyleRationale };
  const candidate = { ...plain, target: { ...f.plan.target as Row, ...decorate } };
  const input = { accepted: f.plan, candidate, manifest: f.manifest, proposal: f.proposal, evidence: f.evidence };
  assertGuidedPresenterCandidate(input); assertGuidedPresenterCandidate({ ...input, candidate: plain });
  for (const patch of [{ width: 1080 }, { scope: "full" }, { lanes: { motion: "off" } }, { extra: true },
    { graphicsStyle: "overlay-rich" }, { graphicsStyleRationale: "Swapped unrequested style explanation." }]) {
    assert.throws(() => assertGuidedPresenterCandidate({ ...input, candidate: { ...candidate, target: { ...candidate.target, ...patch } } }), /target differs/);
  }
  for (const partial of [{ graphicsStyle: decorate.graphicsStyle }, { graphicsStyleRationale: decorate.graphicsStyleRationale }]) {
    assert.throws(() => assertGuidedPresenterCandidate({ ...input, candidate: { ...plain, target: { ...f.plan.target as Row, ...partial } } }), /target differs/);
  }
  const changed = structuredClone(f.proposal); changed.graphicsStyleRationale = "A changed request cannot retroactively explain this target.";
  assert.throws(() => assertGuidedPresenterCandidate({ ...input, proposal: changed }), /target differs/);
  assert.throws(() => assertGuidedPresenterCandidate({ ...input, proposal: { ...f.proposal, schemaVersion: 7 } as unknown as typeof f.proposal }), /Invalid V8/);
});
