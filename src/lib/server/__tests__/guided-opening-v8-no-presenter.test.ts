/** Pure/stub V8 no-work compatibility; no source, provider, media or approval is exercised. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { oldOperation } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import { proposalV8ValidationView } from "@/lib/producer/contracts/treatment-proposal-v8";
import { SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE } from "@/lib/producer/contracts/guided-caption-profile";
import { assertNoPresenterOpening, assertOpeningRequestLanes, OPENING_REQUEST_LANES_SOURCE } from "../guided-opening-request-lanes";
import { assertFullProgramMediaMetadata, assertOpeningMediaMetadata } from "../guided-opening-media-input";
import { buildProposalReadinessPacket, buildProposalReadinessPrompt } from "../guided-proposal-review-packet";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { openingImplementation, type OpeningReadiness } from "../guided-opening-authority";
import { presenterProposal, layoutOperation } from "./_guided-proposal-presenter-fixture";
import { historicalNoPresenterProposal, noPresenterFixture } from "./_guided-opening-v8-no-presenter-fixture";

test("actual no-presenter V8 stays8/2 in readiness and opening/body metadata without inventing a layout", () => {
  const f = noPresenterFixture(), packet = buildProposalReadinessPacket(f.ready);
  assert.equal(packet.proposal.schemaVersion, 8); assert.equal(packet.evidence.schemaVersion, 8);
  assert.equal(packet.executionBindings!.schemaVersion, 2); assert.deepEqual(packet.proposal, f.proposal);
  assert.equal(Object.hasOwn(packet.candidate, "presenterLayouts"), false);
  const metadata = { plan: f.candidate, bindings: f.bindings, proposal: f.proposal, evidence: f.evidence };
  assertOpeningMediaMetadata({ ...metadata, reviewEndFrame: 600 }); assertFullProgramMediaMetadata(metadata);
  assert.match(buildProposalReadinessPrompt(packet, 0), /"schemaVersion":8/);
  assert.equal(canonicalJsonSha256({ plan: f.plan, manifest: f.manifest, packet: f.packet }), f.originalHash);
});

test("mixed prior music/caption/crop lanes are rederived with local views and original packets unchanged", () => {
  for (const short of [false, true]) {
    const f = noPresenterFixture(short, true), profile = short ? SCREENED_CAPTION_SHORT_PROFILE : SCREENED_CAPTION_PROFILE;
    assertOpeningRequestLanes({ accepted: f.plan, candidate: f.candidate, manifest: f.manifest, packet: f.packet, profile });
    assertFullProgramMediaMetadata({ plan: f.candidate, bindings: f.bindings, proposal: f.proposal, evidence: f.evidence });
    assert.deepEqual(f.candidate.music, { enabled: true, assetId: "music-1", gapDb: 11, duck: true });
    assert.deepEqual(f.candidate.captions, { burn: true });
    if (short) assert.deepEqual(f.candidate.reframe, { layout: "fill", crop: [0.5, 0, 0.5, 1], track: false });
    assert.equal(canonicalJsonSha256({ plan: f.plan, manifest: f.manifest, packet: f.packet }), f.originalHash);
  }
});

test("legacy no-presenter entry stays fenced; an unbound selected request cannot acquire current metadata", () => {
  const f = noPresenterFixture();
  for (const value of [[], null, {}, undefined]) {
    assert.throws(() => assertNoPresenterOpening({ ...f, candidate: { ...f.candidate, presenterLayouts: value } }), /own connected media profile/);
  }
  const proposal = presenterProposal([oldOperation("captions-full-program"), layoutOperation()]);
  assert.throws(() => assertNoPresenterOpening({ ...f, proposal }), /no readiness critic/);
  assert.throws(() => buildProposalReadinessPacket({ ...f.ready, result: { ...f.ready.result, proposal } }), /sourceIds differ/);
});

test("unidentified, downgraded, forged or nonempty V2 bindings cannot take the V1 metadata path", () => {
  const f = noPresenterFixture(), metadata = { plan: f.candidate, bindings: f.bindings, proposal: f.proposal, evidence: f.evidence };
  assert.throws(() => assertFullProgramMediaMetadata({ plan: f.candidate, bindings: f.bindings }), /actual V8/);
  for (const patch of [{ schemaVersion: 1 }, { presenterLayouts: null }, { presenterLayouts: [{}] },
    { candidatePlanHash: "f".repeat(64) }, { unknown: true }]) {
    assert.throws(() => assertFullProgramMediaMetadata({ ...metadata, bindings: { ...f.bindings, ...patch } as never }));
  }
  assert.throws(() => assertFullProgramMediaMetadata({ ...metadata, evidence: { ...f.evidence, schemaVersion: 7 } }), /actual V8/);
});

test("rehashed candidate fields and policy mutations cannot replace actual prior-lane requests", () => {
  const f = noPresenterFixture(true, true), profile = SCREENED_CAPTION_SHORT_PROFILE;
  const input = { accepted: f.plan, candidate: f.candidate, manifest: f.manifest, packet: f.packet, profile };
  for (const patch of [{ music: { enabled: true, assetId: "other", gapDb: 11, duck: true } }, { captions: { burn: false } },
    { reframe: { layout: "fill", crop: [0, 0, 1, 1], track: false } }, { target: { ...f.plan.target as object, width: 720 } }]) {
    assert.throws(() => assertOpeningRequestLanes({ ...input, candidate: { ...f.candidate, ...patch } }));
  }
  for (const key of ["musicPolicy", "presenterPolicy"]) {
    assert.throws(() => assertOpeningRequestLanes({ ...input, packet: { ...f.packet, evidence: { ...f.evidence, [key]: {} } } }), /policy|evidence/);
  }
  for (const version of [true, "8", 9]) assert.throws(() => assertOpeningRequestLanes({ ...input,
    packet: { ...f.packet, proposal: { ...f.proposal, schemaVersion: version } } }));
});

test("historical V7 prior-lane validation remains valid and required new helper is explicitly captured", () => {
  const f = noPresenterFixture(false, true), proposal = proposalV8ValidationView(f.proposal as never);
  assertOpeningRequestLanes({ accepted: f.plan, candidate: f.candidate, manifest: f.manifest,
    packet: { ...f.packet, proposal, evidence: { ...f.evidence, schemaVersion: 7 } }, profile: SCREENED_CAPTION_PROFILE });
  for (const file of ["guided-proposal-review-packet.ts", "guided-opening-authority.ts"]) {
    const source = readFileSync(`src/lib/server/${file}`, "utf8");
    assert.match(source, /const REQUIRED = \[[\s\S]*?OPENING_REQUEST_LANES_SOURCE\]/);
  }
  assert.equal(OPENING_REQUEST_LANES_SOURCE, "src/lib/server/guided-opening-request-lanes.ts");
});

test("V2 through V7 requests retain their historical closed operation fields and prior-lane checks", () => {
  const f = noPresenterFixture();
  for (const version of [2, 3, 4, 5, 6, 7]) {
    const proposal = historicalNoPresenterProposal(f.proposal, version), before = structuredClone(proposal);
    assertOpeningRequestLanes({ accepted: f.plan, candidate: f.candidate, manifest: f.manifest,
      packet: { ...f.packet, proposal, evidence: { ...f.evidence, schemaVersion: version } }, profile: SCREENED_CAPTION_PROFILE });
    assert.deepEqual(proposal, before); assert.equal(proposal.schemaVersion, version);
  }
});

test("actual pinned opening implementation rejects missing or mutated new request-lane source", () => {
  const root = mkdtempSync(path.join(realpathSync(tmpdir()), "sniper-v8-noop-closure-"));
  const names = ["src/lib/producer/contracts/guided-opening-v1.ts", "src/lib/server/guided-opening-authority.ts",
    "src/lib/server/guided-opening.ts", "src/lib/server/guided-opening-store.ts", "src/lib/server/guided-proposal-bindings.ts", OPENING_REQUEST_LANES_SOURCE];
  try {
    const files = names.map(name => {
      const bytes = readFileSync(name), destination = path.join(root, name);
      mkdirSync(path.dirname(destination), { recursive: true }); writeFileSync(destination, bytes);
      return { path: name, hash: createHash("sha256").update(bytes).digest("hex") };
    });
    const pipeline = { files, snapshotRoot: root };
    const proposal = { job: { ctx: { pipeline } } } as unknown as OpeningReadiness;
    assert.equal(openingImplementation(proposal).files.at(-1)!.name, OPENING_REQUEST_LANES_SOURCE);
    pipeline.files = files.filter(row => row.path !== OPENING_REQUEST_LANES_SOURCE);
    assert.throws(() => openingImplementation(proposal), /predates required proposal module/);
    pipeline.files = files; writeFileSync(path.join(root, OPENING_REQUEST_LANES_SOURCE), "TEST changed captured source");
    assert.throws(() => openingImplementation(proposal), /differs from pinned implementation/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
