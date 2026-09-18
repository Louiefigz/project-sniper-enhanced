/** Opt-in full private short TEST chain. Never accepts an existing project, creator source or approval. */
import assert from "node:assert/strict";
import path from "node:path";
import type { TestContext } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { SCREENED_CAPTION_SHORT_PROFILE } from "@/lib/producer/contracts/guided-caption-profile";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { assertBodyGraphWorkload } from "@/lib/producer/contracts/guided-body-media-v1";
import { assertFullProgramMediaMetadata, observeGuidedOpeningMediaInput, openingMediaAuthority } from "../guided-opening-media-input";
import { readSelectedOpeningMedia } from "../guided-opening-selection";
import { readHeldOpeningResult } from "../guided-opening-result";
import { createV6ShortBootstrapFixture } from "./_guided-v6-short-fixture";
import { compileV6ShortReadiness, CROP, RAW_V6_SHORT } from "./_guided-v6-short-proposal";
import { bindV6ShortSynthetic } from "./_guided-v6-short-live-guard";
import { launchLiveOpening, approveLiveSynthetic, generateLiveBody, type SyntheticLiveFlow } from "./_guided-body-live-flow";
import { bodyLiveRuntimeControls, newBodyLiveLog, retainBodyLive, timedBodyLive } from "./_guided-body-live-support";

export const V6_SHORT_MEDIA_OPT_IN = "SNIPER_RUN_V6_SHORT_MEDIA";
export const V6_SHORT_MEDIA_OBSERVATION_MS = 150 * 60_000;
const SCOPE = "TEST-only-fresh-V6-short-full-private-mechanics-not-creator-or-delivery-approval";
type Fixture = Awaited<ReturnType<typeof createV6ShortBootstrapFixture>>;
type Readiness = Awaited<ReturnType<typeof compileV6ShortReadiness>>;

/** No graphic work is requested: actual envelope evidence is required, but it cannot claim visual QC. */
export function assertShortNoGraphicsScreen(value: unknown, projectionHash: string) {
  const row = objectValue(value, "actual short caption layout screen");
  const keys = ["schemaVersion", "policy", "scope", "state", "clock", "coverage", "captionProjectionHash",
    "inputHash", "graphics", "qcPassed", "creativeApproved", "deliveryApproved"];
  exactKeys(row, keys, keys, "actual short caption layout screen");
  assert.equal(row.schemaVersion, 2); assert.equal(row.policy, "native-caption-layout-screen-v2");
  assert.equal(row.scope, "held-envelope-screen-not-pixel-legibility-or-creative-approval");
  assert.equal(row.state, "not-applicable"); assert.deepEqual(row.graphics, []);
  assert.deepEqual(row.clock, { frameRate: "30/1", totalFrames: 480, width: 1080, height: 1920 });
  assert.deepEqual(row.coverage, { startFrame: 0, endFrameExclusive: 480 });
  assert.equal(row.captionProjectionHash, sha256(projectionHash, "actual original caption hash")); sha256(row.inputHash, "screen input hash");
  for (const key of ["qcPassed", "creativeApproved", "deliveryApproved"]) assert.equal(row[key], false);
  return row;
}

/** This setup guard never replaces or replenishes the later production generation clock. */
export function shortSetupRemaining(started: number, signal: AbortSignal): () => number {
  if (!Number.isFinite(started) || started < 0 || started > performance.now()) throw new Error("Malformed original TEST setup clock");
  return () => {
    const remaining = Math.floor(600_000 - (performance.now() - started));
    if (signal.aborted || remaining < 1000) throw new Error("Original10-minute short TEST setup cap expired; no retry");
    return remaining;
  };
}

function assertCandidate(readiness: Readiness): void {
  const { result } = readiness, candidate = result.candidate!;
  assert.equal(result.proposal.schemaVersion, 6); assert.ok(candidate);
  assert.deepEqual(candidate.reframe, { layout: "fill", crop: CROP, track: false });
  assert.deepEqual(candidate.captions, { burn: true });
  assert.ok(candidate.captionsTrack);
  assert.deepEqual(result.proposal.operations.map((op) => op.type), ["reframe-manual-short", "captions-full-program"]);
  assert.equal(result.proposal.clauses.map((clause) => clause.quote).join(""), RAW_V6_SHORT);
  const media = openingMediaAuthority(readiness);
  assertFullProgramMediaMetadata({ plan: candidate, bindings: media.bindings });
  assert.equal(media.bindings.graphics.length, 0);
  assertBodyGraphWorkload(media.authority.target, 0);
}

function selectedInput(fixture: Fixture, selected: Awaited<ReturnType<typeof launchLiveOpening>>, readiness: Readiness) {
  const current = readSelectedOpeningMedia(fixture.dir);
  assert.equal(current.selectionHash, selected.selectionHash);
  assert.equal(current.held.claim.requestId, selected.requestId);
  assert.equal(current.held.claim.executionId, selected.executionId);
  const { inputPath, inputSha256 } = current.held.claim;
  const result = readHeldOpeningResult(current.held).record.value;
  const full = objectValue(result.fullProgram, "actual opening full program"), ref = objectValue(full.captionProjection, "actual original caption projection");
  assert.equal(ref.path, path.join(current.held.claim.outputRoot, "full-program-base", "guided-caption-projection.json"));
  const projection = readCutPreviewObject(String(ref.path)); assert.equal(projection.sha256, ref.sha256);
  const captionHash = sha256(projection.value.dataHash, "original caption projection data hash");
  const screen = assertShortNoGraphicsScreen(result.captionLayoutScreen, captionHash);
  const observed = observeGuidedOpeningMediaInput(inputPath, inputSha256), docs = observed.documents;
  assert.equal(Object.keys(docs).length, 14); assert.equal(observed.authority.profile, SCREENED_CAPTION_SHORT_PROFILE);
  assert.equal(docs.acceptedPlan.sha256, fixture.saved.sha256);
  assert.deepEqual(docs.candidatePlan.value, readiness.result.candidate);
  assert.deepEqual(docs.readinessPacket.value.proposal, readiness.result.proposal);
  assert.deepEqual(docs.candidatePlan.value.cutTrack, docs.acceptedPlan.value.cutTrack);
  assert.deepEqual(docs.candidatePlan.value.cutDecisions, docs.acceptedPlan.value.cutDecisions);
  for (const row of Object.values(selected.media)) {
    assert.equal(row.width, 1080); assert.equal(row.height, 1920); assert.equal(row.frameRate, "30/1");
    assert.equal(row.startFrame, 0); assert.equal(row.endFrameExclusive, 480); assert.equal(row.videoFrames, 480);
  }
  return { inputPath, inputSha256, observed, captionHash, screen };
}

function assertFinalShort(body: Awaited<ReturnType<typeof generateLiveBody>>, captionHash: string) {
  const file = path.join(path.dirname(path.dirname(body.candidate.path)), "body-result.json");
  const record = readCutPreviewObject(file), media = objectValue(record.value.media, "actual short body media");
  const final = objectValue(media.final, "actual short final picture"), delivery = objectValue(media.programDelivery, "actual short full-master delivery");
  assert.equal(final.path, body.candidate.path); assert.equal(final.sha256, body.candidate.sha256);
  assert.equal(final.width, 1080); assert.equal(final.height, 1920); assert.equal(final.frameRate, "30/1"); assert.equal(final.frames, 480);
  assert.equal(delivery.audiblePathAacEncodes, 1); assert.equal(delivery.samples, 768_000);
  assert.equal(record.value.bodyApproved, false); assert.equal(record.value.deliveryApproved, false);
  assert.ok(Array.isArray(media.captionSupport) && media.captionSupport.length > 0);
  const screen = assertShortNoGraphicsScreen(record.value.captionLayoutScreen, captionHash);
  return { receiptPath: file, receiptSha256: record.sha256, stages: record.value.stages,
    shortGeometry: { width: final.width, height: final.height, frames: final.frames, frameRate: final.frameRate },
    programDelivery: delivery, captionSupport: media.captionSupport, captionLayoutScreen: screen };
}

async function fullShortChain(fixture: Fixture, scope: SyntheticLiveFlow, remaining: () => number) {
  const { dir, log, assertSynthetic } = scope;
  // The callback executes immediately before the helper constructs its TEST cut attestation.
  const readiness = await timedBodyLive(log, "v6-cut-test-acceptance-through-readiness", () => compileV6ShortReadiness(dir, () => {
    assertSynthetic(); return remaining();
  }));
  assertSynthetic(); assertCandidate(readiness);
  retainBodyLive(log, "v6-real-readiness-metadata.json", { scope: SCOPE, rawIntent: RAW_V6_SHORT,
    proposal: readiness.result.proposal, candidate: readiness.result.candidate, readinessHash: readiness.readinessHash });
  const selected = await launchLiveOpening(log, dir), input = selectedInput(fixture, selected, readiness);
  retainBodyLive(log, "v6-actual-launched-input.json", { inputPath: input.inputPath, inputSha256: input.inputSha256,
    profile: input.observed.authority.profile, documentCount: Object.keys(input.observed.documents).length, captionLayoutScreen: input.screen,
    scope: "actual-opening-launch-input-not-a-separate-prepare-only-attempt" });
  const approved = await approveLiveSynthetic(scope, selected);
  const body = await generateLiveBody(scope, approved, true), actual = assertFinalShort(body, input.captionHash);
  assertSynthetic();
  assert.deepEqual(observeGuidedOpeningMediaInput(input.inputPath, input.inputSha256).input, input.observed.input);
  return { body, actual, originalGenerationStartedAt: selected.timing.generationStartedAt };
}

/** In-process bootstrap transport only; all subsequent render/cleanup/readback use unchanged production CLIs. */
export async function runV6ShortLiveFixture(t: TestContext) {
  if (process.env[V6_SHORT_MEDIA_OPT_IN] !== "1") throw new Error("Full short TEST requires exact explicit opt-in; no work started");
  assert.equal(CURRENT_TREATMENT_PROPOSAL_VERSION, 5, "Internal V6 fixture must not activate the production default");
  const began = performance.now(), startedAt = new Date().toISOString(), remaining = shortSetupRemaining(began, t.signal);
  const controls = bodyLiveRuntimeControls(), fixture = await createV6ShortBootstrapFixture(t, remaining);
  const log = newBodyLiveLog(fixture.workspace); log.began = began;
  retainBodyLive(log, "test-scope.json", { scope: SCOPE, controls, startedAt, sourceBootstrapElapsedMs: performance.now() - began,
    actualAsr: false, genuineHumanAcceptance: false, creativeQualityQualified: false, detachedBootstrapQualified: false,
    fixtureClass: "16-second full-program opening; no later-body or crossing-page qualification", defaultProposalVersion: 5 });
  try {
    const scope = { log, dir: fixture.dir, assertSynthetic: bindV6ShortSynthetic(fixture) };
    const chain = await fullShortChain(fixture, scope, remaining);
    const result = { state: "TEST-V6-short-private-body-mechanics-passed", scope: SCOPE, workspace: fixture.workspace,
      dir: fixture.dir, elapsedMs: performance.now() - began, ...chain,
      actualAsr: false, genuineHumanAcceptance: false, creativeQualityQualified: false, bodyApproved: false, deliveryApproved: false };
    retainBodyLive(log, "result.json", result); return result;
  } catch (error) {
    retainBodyLive(log, "failed.json", { scope: SCOPE, error: String(error), stack: error instanceof Error ? error.stack : null,
      elapsedMs: performance.now() - began, artifactsPreserved: true, automaticRetry: false, cleanupClaim: "not-inferred-by-test-driver" });
    throw error;
  }
}
