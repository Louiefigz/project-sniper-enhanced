import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { BODY_MEDIA_REFERENCES, parseCurrentBodyMediaInput as parseGuidedBodyMediaInput, assertBodyGraphWorkload,
  type BodyFileReference, type CurrentGuidedBodyMediaInput } from "@/lib/producer/contracts/guided-body-media-v1";
import { parseBodySourceColorReplayReferences, type BodySourceColorReplayReferencesV2 } from "@/lib/producer/contracts/guided-body-source-color-replay-v2";
import { assertFullProgramMediaMetadata, observeGuidedOpeningMediaInput, openingMediaAuthority } from "./guided-opening-media-input";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { captureOpeningRuntimeControl } from "./guided-opening-runtime-control";
import { createOpeningRecord, assertOpeningRecord } from "./guided-opening-process-activation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertBodyClaimSourceColorMetadata, bodyAdmissionInputVersion, type readGuidedBodyClaim } from "./guided-body-lineage";
import { currentBodyMediaProfile } from "./guided-opening-profile";
import { objectValue } from "@/lib/producer/contracts/validation";
import { directoryIdentity, fileIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { parseBodyHeldDocument } from "./guided-body-store";
import { holdBodyControllerSources } from "./guided-body-controller-sources";
import { retainBodyControllerInvocation } from "./guided-body-controller-handoff";

export type BodyAdmission = ReturnType<typeof readGuidedBodyClaim>;
/** Code-only metadata TEST leaves; actual admission, raw references, validation and publication stay hardwired. */
export const guidedBodyInputReads = { readiness: readGuidedProposalReadiness, mediaAuthority: openingMediaAuthority,
  runtime: captureOpeningRuntimeControl, opening: observeGuidedOpeningMediaInput };

function reference(file: string, expected: string): BodyFileReference {
  const row = readCutPreviewObject(file);
  if (row.sha256 !== expected) throw new Error("Body input reference differs from exact admission-held bytes");
  return { path: file, sha256: expected };
}

function references(held: BodyAdmission): CurrentGuidedBodyMediaInput["references"] {
  const { claim, execution, input } = held;
  return { admissionClaim: reference(path.join(execution, "claim.json"), held.claimHash),
    heldInput: reference(path.join(execution, "held-input.json"), claim.heldInputHash),
    approvedSnapshot: reference(held.snapshotPath, held.before.sha256),
    openingInput: reference(String(input.opening.inputPath), String(input.opening.inputSha256)),
    openingResult: reference(String(input.opening.resultPath), String(input.opening.resultSha256)),
    budgetAdmission: reference(path.join(execution, "budget-admission.json"), claim.budgetAdmissionHash),
    budgetPrecommit: reference(path.join(execution, "budget-precommit.json"), claim.budgetPrecommitHash) };
}

/** Exact provenance references must match the validated admission, not merely a mutually consistent new document. */
export function assertBodyInputReferences(held: BodyAdmission, input: CurrentGuidedBodyMediaInput): void {
  const source = sourceColorInput(held, () => {});
  if (input.requestId !== held.claim.requestId || input.executionId !== held.claim.executionId
      || input.schemaVersion !== source.fields.schemaVersion
      || input.profile !== currentBodyMediaProfile(objectValue(held.input.input.authority, "body held authority").profile)
      || canonicalJsonSha256(input.references) !== canonicalJsonSha256(references(held))) {
    throw new Error("Body input replaced its original admission-held provenance");
  }
  if (input.schemaVersion === 2 && canonicalJsonSha256(input.sourceColorReplay) !== canonicalJsonSha256(source.fields.sourceColorReplay)) {
    throw new Error("Body input replaced its original source-color replay");
  }
  source.assertMetadata?.();
}

/** Bounded original replay files only; no payload parsing, sources, current journal or native tools. */
function observeReplay(replay: BodySourceColorReplayReferencesV2): void {
  for (const reference of [replay.input, replay.reservationArchive]) {
    const observed = observeCutPreviewFile(reference.path, 8 * 1024 * 1024);
    if (observed.sha256 !== reference.sha256 || observed.sizeBytes !== reference.sizeBytes) {
      throw new Error("Body source-color replay differs from original raw metadata bytes or size");
    }
  }
}

/** Capture version/replay BEFORE the first caller callback; only the actual lineage hold authenticates V2. */
function sourceColorInput(held: BodyAdmission, guard: () => void) {
  const version = bodyAdmissionInputVersion(held), stored = storedBodyInput(held);
  if (version === 1) return { fields: { schemaVersion: 1 as const }, guard, assertMetadata: undefined };
  assertBodyClaimSourceColorMetadata(held);
  const replay = parseBodySourceColorReplayReferences(held.input.input.sourceColorReplay), opening = held.input.opening;
  if (replay.opening.inputSha256 !== opening.inputSha256
      || replay.opening.executionInputHash !== opening.executionInputHash || replay.opening.mediaResultSha256 !== opening.resultSha256
      || replay.opening.selectionHash !== held.input.input.selectionHash
      || path.dirname(String(opening.claimPath)) !== path.dirname(path.dirname(replay.input.path))) {
    throw new Error("Body source-color replay moved from the original opening");
  }
  const assertMetadata = () => {
    assertBodyClaimSourceColorMetadata(held); stored();
    if (held.input.row.schemaVersion !== 2 || held.input.input.schemaVersion !== 2
        || canonicalJsonSha256(held.input.input.sourceColorReplay) !== canonicalJsonSha256(replay)) {
      throw new Error("Body original source-color version or replay changed");
    }
  };
  observeReplay(replay); assertMetadata();
  return { fields: { schemaVersion: 2 as const, sourceColorReplay: replay },
    guard: () => { assertMetadata(); guard(); assertMetadata(); }, assertMetadata };
}

/** Compare the actual claim-held document, so a copied source2 row cannot downgrade itself to legacy. */
function storedBodyInput(held: BodyAdmission): () => void {
  const file = path.join(held.execution, "held-input.json"), check = publishedMetadata(file);
  const original = readCutPreviewObject(file);
  if (original.sha256 !== held.claim.heldInputHash || !isDeepStrictEqual(parseBodyHeldDocument(original.value), held.input)) {
    throw new Error("Body original stored held-input version or metadata differs");
  }
  check(); return check;
}

/** Original publication identity, retained before the post-write callback; not a reusable admission capability. */
function publishedMetadata(file: string): () => void {
  const original = fileIdentity(file), parents = new Map<string, bigint[]>();
  for (let directory = path.dirname(file);; directory = path.dirname(directory)) {
    parents.set(directory, directoryIdentity(directory)); if (path.dirname(directory) === directory) break;
  }
  return () => {
    for (const [directory, identity] of parents) {
      if (!isDeepStrictEqual(directoryIdentity(directory), identity)) throw new Error("Body input publication parent changed");
    }
    if (!isDeepStrictEqual(fileIdentity(file), original)) throw new Error("Body input original publication changed");
  };
}

/** Current full pinned metadata checks; actual source/master/media observations still belong to the owned worker. */
export function bodyMediaMetadata(held: BodyAdmission) {
  const proposal = guidedBodyInputReads.readiness(held.before.job.ctx.dir);
  const media = guidedBodyInputReads.mediaAuthority(proposal, objectValue(held.input.input.authority, "body held authority").profile);
  if (proposal.sha256 !== held.current.sha256 || canonicalJsonSha256(media.authority) !== canonicalJsonSha256(held.input.input.authority)
      || canonicalJsonSha256(media.bindings) !== canonicalJsonSha256(held.input.input.bindings)) throw new Error("Body current candidate authority changed");
  assertFullProgramMediaMetadata({ plan: proposal.result.candidate!, bindings: media.bindings,
    proposal: proposal.result.proposal, evidence: proposal.evidence, accepted: proposal.plan.value, manifest: proposal.manifest.value });
  assertBodyGraphWorkload(media.authority.target, media.bindings!.graphics.length);
  const original = guidedBodyInputReads.opening(String(held.input.opening.inputPath), String(held.input.opening.inputSha256));
  if (canonicalJsonSha256(original.authority) !== canonicalJsonSha256(media.authority)) throw new Error("Body original opening input authority changed");
  return { proposal, profile: currentBodyMediaProfile(media.authority.profile), orders: media.bindings!.graphics.map((row) => row.order) };
}

/** New-only worker metadata, after actual admission. No mutable directory pointer can select a base or master. */
export function writeGuidedBodyMediaInput(held: BodyAdmission, guard: () => void, remainingMs?: () => number) {
  const source = sourceColorInput(held, guard);
  if (source.fields.schemaVersion === 2 && typeof remainingMs !== "function") throw new Error("Body controller requires the original remaining budget");
  const controller = source.fields.schemaVersion === 2 ? holdBodyControllerSources({ admission: held, remainingMs: remainingMs! }) : undefined;
  const check = () => { controller?.assertMetadata(); source.guard(); controller?.check(); };
  check(); const metadata = bodyMediaMetadata(held); check();
  const input = parseGuidedBodyMediaInput({ ...source.fields, kind: "guided-body-media-input", scope: "private-body-candidate-not-approval",
    profile: metadata.profile, requestId: held.claim.requestId, executionId: held.claim.executionId,
    references: references(held), runtime: guidedBodyInputReads.runtime(metadata.proposal), selectedGraphicOrders: metadata.orders });
  check(); const record = createOpeningRecord(path.join(held.execution, "body-media-input.json"), { ...input });
  const publication = source.assertMetadata ? publishedMetadata(record.path) : undefined;
  observeGuidedBodyMediaInput(record.path, record.sha256); assertOpeningRecord(record); check(); publication?.(); source.assertMetadata?.();
  const result = { input, record };
  retainBodyControllerInvocation(result, controller); return result;
}

/** Exact byte references only, not current journal/source freshness or execution permission. */
export function observeGuidedBodyMediaInput(file: string, expected: string) {
  const record = observeCutPreviewFile(file, 128 * 1024, true);
  if (record.sha256 !== expected) throw new Error("Body invocation input changed");
  const input = parseGuidedBodyMediaInput(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(record.bytes)));
  const held = input.schemaVersion === 2
    ? [file, input.sourceColorReplay.input.path, input.sourceColorReplay.reservationArchive.path].map(publishedMetadata) : [];
  BODY_MEDIA_REFERENCES.forEach((name) => reference(input.references[name].path, input.references[name].sha256));
  if (input.schemaVersion === 2) observeReplay(input.sourceColorReplay);
  if (readCutPreviewObject(file).sha256 !== expected) throw new Error("Body input changed during observation");
  held.forEach(check => check());
  return { input, record, sourceBytesObserved: false as const, currentJournalObserved: false as const };
}
