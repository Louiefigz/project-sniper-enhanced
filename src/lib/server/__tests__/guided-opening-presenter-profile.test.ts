/** Pure metadata + inert JSON files only. No real cut/source authority, provider, media, Docker or human approval. */
import assert from "node:assert/strict";
import { randomUUID, createHash } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { presenterReaderContext, presenterReadinessStub, writePresenterDocuments, TEST_PRESENTER_HASH } from "./_guided-opening-presenter-documents";
import { openingProfileForContext, currentBodyMediaProfile, PRESENTER_OPENING_PROFILE_FILES } from "../guided-opening-profile";
import { assertOpeningMediaMetadata, assertFullProgramMediaMetadata, observeGuidedOpeningMediaInput } from "../guided-opening-media-input";
import { assertOpeningRequestLanes, OPENING_REQUEST_LANES_SOURCE } from "../guided-opening-request-lanes";
import { openingImplementation, type OpeningReadiness } from "../guided-opening-authority";
import { buildProposalReadinessPacket } from "../guided-proposal-review-packet";
import { parseCurrentOpeningMediaInput, parseCurrentOpeningMediaAuthority, parseGuidedOpeningMediaInput,
  parseGuidedOpeningMediaAuthority } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parseCurrentBodyMediaInput, parseGuidedBodyMediaInput, BODY_MEDIA_REFERENCES } from "@/lib/producer/contracts/guided-body-media-v1";
import { PRESENTER_PROFILE, PRESENTER_SHORT_PROFILE, PRESENTER_CAPTION_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE } from "@/lib/producer/contracts/guided-presenter-profile";
import { canonicalJson, canonicalJsonSha256 as hash } from "../auto-edit-hash";

function scratch() { return mkdtempSync(path.join(realpathSync(tmpdir()), "sniper-presenter-metadata-")); }
function bodyInput(profile: string) {
  const sha = TEST_PRESENTER_HASH;
  return { schemaVersion: 1, kind: "guided-body-media-input", scope: "private-body-candidate-not-approval", profile,
    requestId: randomUUID(), executionId: randomUUID(), selectedGraphicOrders: [],
    references: Object.fromEntries(BODY_MEDIA_REFERENCES.map(name => [name, { path: `/private/tmp/TEST/${name}.json`, sha256: sha }])),
    runtime: { dockerPath: "/private/tmp/TEST/docker", dockerSha256: sha, dockerSocketPath: "/private/tmp/TEST/socket",
      dockerSocketDevice: "1", dockerSocketInode: "2", imageId: `sha256:${sha}`, userId: "501:20",
      imageApprovalPath: "/private/tmp/TEST/approval.json", imageApprovalSha256: sha, runtimeRepoRoot: "/private/tmp/TEST/repo" } };
}

test("four current token pairs parse exact metadata while every historical parser remains closed", () => {
  for (const [short, captioned] of [[false, false], [true, false], [false, true], [true, true]]) {
    const root = scratch();
    try {
      const context = presenterReaderContext(short, captioned), built = writePresenterDocuments(root, context);
      assert.deepEqual(parseCurrentOpeningMediaInput(built.value), built.value);
      assert.deepEqual(parseCurrentOpeningMediaAuthority(built.docs.authority), built.docs.authority);
      assert.throws(() => parseGuidedOpeningMediaInput(built.value)); assert.throws(() => parseGuidedOpeningMediaAuthority(built.docs.authority));
      const body = bodyInput(currentBodyMediaProfile(built.value.profile));
      assert.deepEqual(parseCurrentBodyMediaInput(body), body); assert.throws(() => parseGuidedBodyMediaInput(body));
      assert.throws(() => parseCurrentOpeningMediaInput({ ...built.value, profile: body.profile }));
      assert.throws(() => parseCurrentBodyMediaInput({ ...body, profile: built.value.profile }));
    } finally { rmSync(root, { recursive: true, force: true }); }
  }
});

test("fresh selection and actual8/2 readiness preserve full request metadata and all inputs", () => {
  const input = presenterReaderContext(false, true), before = structuredClone(input);
  const profile = openingProfileForContext(input); assert.equal(profile, PRESENTER_CAPTION_PROFILE);
  const packet = buildProposalReadinessPacket(presenterReadinessStub(input));
  assert.deepEqual(packet.proposal, input.proposal); assert.deepEqual(packet.candidate, input.candidate);
  assert.deepEqual(packet.executionBindings, input.bindings); assert.equal(packet.evidence.schemaVersion, 8);
  assertOpeningRequestLanes({ ...input, profile, packet });
  const metadata = { ...input, plan: input.candidate, bindings: packet.executionBindings!, proposal: packet.proposal, reviewEndFrame: 600 };
  assertOpeningMediaMetadata(metadata); assertFullProgramMediaMetadata(metadata); assert.deepEqual(input, before);
  assert.equal(Object.hasOwn(packet, "presenterCaptionClearance"), false);
  assert.equal(Object.hasOwn(packet, "captionLayoutScreen"), false);
});

test("metadata-only cold reader reconstructs all14 original documents, with no source/pipeline/media observation claim", () => {
  for (const [short, captioned] of [[false, false], [true, false], [false, true], [true, true]]) {
    const root = scratch();
    try {
      const input = presenterReaderContext(short, captioned), built = writePresenterDocuments(root, input);
      const read = observeGuidedOpeningMediaInput(built.ref.path, built.ref.sha256);
      assert.equal(Object.keys(read.documents).length, 14); assert.equal(read.authority.profile, openingProfileForContext(input));
      assert.deepEqual(read.documents.readinessPacket.value.proposal, input.proposal);
      assert.equal(read.documents.readinessPacket.value.evidence && (read.documents.readinessPacket.value.evidence as { schemaVersion: number }).schemaVersion, 8);
      assert.equal(read.documents.frameBindings.value.schemaVersion, 2);
      assert.equal(read.authority.candidatePlanHash, hash(input.candidate));
      assert.equal(read.sourceBytesObserved, false); assert.equal(read.currentJournalObserved, false); assert.equal(read.pipelineFilesObserved, false);
    } finally { rmSync(root, { recursive: true, force: true }); }
  }
});

test("cold intake cannot swap, drop, rehash or downgrade original selected layout context", () => {
  const input = presenterReaderContext(false, true), profile = openingProfileForContext(input);
  for (const held of [PRESENTER_PROFILE, PRESENTER_SHORT_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE, "unity-source-float-own-screen-caption-layout-v2"]) {
    assert.throws(() => openingProfileForContext(input, held), /no legacy upgrade or downgrade/);
  }
  const packet = buildProposalReadinessPacket(presenterReadinessStub(input));
  assert.throws(() => assertOpeningRequestLanes({ ...input, profile: PRESENTER_PROFILE, packet }), /exact declared media profile/);
  assert.throws(() => assertFullProgramMediaMetadata({ plan: input.candidate, bindings: packet.executionBindings!,
    proposal: packet.proposal, evidence: input.evidence }), /presenter accepted plan/);
  const root = scratch();
  try {
    const built = writePresenterDocuments(root, input);
    const candidatePath = built.value.documents.candidatePlan.path;
    const original = readFileSync(candidatePath);
    writeFileSync(candidatePath, JSON.stringify({ ...input.candidate, presenterLayouts: [] }));
    assert.throws(() => observeGuidedOpeningMediaInput(built.ref.path, built.ref.sha256), /document changed/);
    writeFileSync(candidatePath, original);
    const altered = { ...built.value, profile: PRESENTER_PROFILE }, { executionInputHash: _old, ...core } = altered; void _old;
    const value = { ...core, executionInputHash: hash(core) }; writeFileSync(built.ref.path, canonicalJson(value));
    assert.throws(() => observeGuidedOpeningMediaInput(built.ref.path, hash(value)), /no legacy upgrade or downgrade/);
  } finally { rmSync(root, { recursive: true, force: true }); }
  assert.equal(openingProfileForContext(input, profile), profile);
});

test("selected presenter metadata requires both newly captured helpers; old closure omission is not a runtime fallback", () => {
  const root = scratch(), input = presenterReaderContext(false, false);
  const names = ["src/lib/producer/contracts/guided-opening-v1.ts", "src/lib/server/guided-opening-authority.ts",
    "src/lib/server/guided-opening.ts", "src/lib/server/guided-opening-store.ts", "src/lib/server/guided-proposal-bindings.ts",
    OPENING_REQUEST_LANES_SOURCE, ...PRESENTER_OPENING_PROFILE_FILES];
  try {
    const files = names.map(name => {
      const bytes = readFileSync(name), file = path.join(root, name); mkdirSync(path.dirname(file), { recursive: true }); writeFileSync(file, bytes);
      return { path: name, hash: createHash("sha256").update(bytes).digest("hex") };
    });
    const pipeline = { files, snapshotRoot: root }, proposal = { ...presenterReadinessStub(input), job: { ctx: { pipeline } } } as unknown as OpeningReadiness;
    assert.equal(openingImplementation(proposal).files.length, names.length);
    for (const required of PRESENTER_OPENING_PROFILE_FILES) {
      pipeline.files = files.filter(row => row.path !== required);
      assert.throws(() => openingImplementation(proposal), /predates required proposal module/);
    }
    pipeline.files = files; writeFileSync(path.join(root, PRESENTER_OPENING_PROFILE_FILES[2]), "TEST changed workload implementation");
    assert.throws(() => openingImplementation(proposal), /differs from pinned implementation/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
