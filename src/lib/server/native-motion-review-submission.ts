/** Typed submission of an independent critic's moving-preview judgment as a MOTION-REVIEW bundle. */
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { assertNativeMotionReviewBundle } from "./native-motion-review";
import { reviewCoverage, reviewEvidence, reviewIdentity, type NativePrebuildReviewBinding } from "./native-short-prebuild-review";
import { assertPacketCurrent, canonicalInput, canonicalOutput, engineRoots, frozenArtifact, publishValidatedJson,
  readRolePacket, reviewSpan, stopwatch, type RolePacket } from "./native-review-packet";
import { assertClaimsObserved, bindEvidence, bindInspection, frameClock, frameInteger, readObservations, recordBlocks,
  recordSubmission, type FrameClock, type Observations } from "./native-review-observations";
import { assertApprovals, assertBoundToTargets, assertFrameSeen, assertGapsStated, canonicalizedInputs, observedSpans,
  readInspection, typedEvidence, type Inspection, type ReviewSubmissionPaths, type ReviewTarget } from "./native-review-submission-shared";
import { readApprovedContent } from "./native-review-approved-content";

interface Preview { path: string; sha256: string; value: JsonRecord; packet: JsonRecord; clock: FrameClock; clips: ReviewTarget[] }

function readPreview(packet: RolePacket): Preview {
  const file = stringValue(objectValue(packet.subject.preview, "role packet preview").path, "preview path", 4096);
  const frozen = frozenArtifact(packet, file), observed = readCutPreviewObject(file);
  if (observed.sha256 !== frozen.sha256) throw new Error("Stale review inputs: the moving-preview record changed");
  const value = objectValue(observed.value, "moving-preview record"), region = objectValue(value.packet, "region packet");
  if (value.status !== "native-motion-previews-complete" || !Array.isArray(value.clips) || !value.clips.length) {
    throw new Error("The reviewed preview is not a completed moving-preview record with clips");
  }
  const canvas = objectValue(region.canvas, "region canvas");
  return { path: file, sha256: observed.sha256, value, packet: region, clock: frameClock(canvas.frameRate, canvas.totalFrames),
    clips: value.clips.map((clip, index) => {
      const row = objectValue(clip, `preview clip ${index}`);
      return { path: canonicalInput(stringValue(row.path, `preview clip ${index} path`, 4096), `preview clip ${index}`),
        sha256: sha256(row.sha256, `preview clip ${index} hash`),
        startFrame: row.startFrame as number, endFrameExclusive: row.endFrameExclusive as number };
    }) };
}

/** Frame-numbered notes for one window; a note is admitted only where someone looked at that window's bytes. */
function windowNotes(value: unknown, clip: ReviewTarget, index: number, context: { inspection: Inspection; clock: FrameClock }) {
  const row = objectValue(value, `windows[${index}]`), keys = ["startFrame", "endFrameExclusive", "observations"];
  exactKeys(row, keys, keys, `windows[${index}]`);
  if (row.startFrame !== clip.startFrame || row.endFrameExclusive !== clip.endFrameExclusive) {
    throw new Error(`windows[${index}] must be frames ${clip.startFrame}–${clip.endFrameExclusive} of the reviewed preview`);
  }
  if (!Array.isArray(row.observations)) throw new Error(`windows[${index}].observations must be an array`);
  if (!row.observations.length && observedSpans(context.inspection, clip).length) {
    throw new Error(`windows[${index}] was inspected: it needs frame-numbered observations of what was actually seen`);
  }
  for (const [at, item] of row.observations.entries()) {
    const label = `windows[${index}].observations[${at}]`, note = objectValue(item, label);
    exactKeys(note, ["frame", "note"], ["frame", "note"], label);
    const frame = frameInteger(note.frame, `${label}.frame`, context.clock);
    if (frame < clip.startFrame || frame >= clip.endFrameExclusive) throw new Error(`windows[${index}] observation frame ${frame} is outside the window`);
    assertFrameSeen(context.inspection, clip, frame, label);
    stringValue(note.note, `${label}.note`, 1000);
  }
}

/** Bind the typed entries, then refuse stale bytes, unbacked approvals, unseen notes and located claims, and unstated gaps. */
function checkedInspection(observations: Observations, packet: RolePacket, evidence: NativePrebuildReviewBinding[], preview: Preview) {
  const inspection = bindInspection(observations, packet, evidence), windows = observations.value.windows;
  assertBoundToTargets(inspection, preview.clips);
  assertApprovals(inspection, preview.clips, String(observations.review.verdict));
  if (!Array.isArray(windows) || windows.length !== preview.clips.length) {
    throw new Error(`windows must list all ${preview.clips.length} preview windows in order`);
  }
  windows.forEach((row, index) => windowNotes(row, preview.clips[index], index, { inspection, clock: preview.clock }));
  assertClaimsObserved(observations, inspection, preview.clips);
  assertGapsStated(inspection, preview.clips, observations.limitations);
  return inspection;
}

function reviewedUnits(preview: Preview): Record<string, string> {
  const changed = preview.value.changedUnits, units = preview.packet.units;
  if (!Array.isArray(changed) || !changed.length || !Array.isArray(units)) throw new Error("The preview has no changed units to review");
  return Object.fromEntries(changed.map(id => {
    const unit = units.map(row => objectValue(row, "region unit")).find(row => row.id === id);
    if (!unit) throw new Error(`Changed unit ${String(id)} is missing from the region packet`);
    return [id as string, sha256(unit.hash, "region unit hash")];
  }));
}

/** Earlier rows kept for reused units: passing, independent and typed with a motion approval. A TEST route-canary
 * declaration is never retained (readInspection refuses it outside the fixture gate). */
function retainedRows(packet: RolePacket): unknown[] {
  const retention = packet.subject.retention === undefined ? null : objectValue(packet.subject.retention, "retention");
  const missing = retention?.missingUnits;
  if (Array.isArray(missing) && missing.length) {
    throw new Error(`The preview reuses units ${missing.join(", ")} without a retained current review; re-resolve the `
      + "packet with --prior-reviews <earlier MOTION-REVIEW record>");
  }
  if (!retention?.record) return [];
  const record = objectValue(retention.record, "retained record"), file = stringValue(record.path, "retained record", 4096);
  const observed = readCutPreviewObject(file);
  if (observed.sha256 !== frozenArtifact(packet, file).sha256) throw new Error("Stale review inputs: the retained review record changed");
  const reviews = objectValue(observed.value, "retained record").reviews as unknown[];
  return (retention.rows as number[]).map(index => {
    const row = objectValue(reviews[index], `retained review ${index}`), review = validateProducerReview(row.review, "plan");
    const reviewer = reviewIdentity(row.reviewer);
    const motion = row.inspection !== undefined && readInspection(row.inspection).approves.includes("motion");
    if (review.verdict !== "pass" || review.materialIssues.length || packet.authorSessionIds.includes(reviewer.sessionId) || !motion) {
      throw new Error(`Retained review ${index} is not a passing independent typed motion review; re-resolve the packet`);
    }
    return row;
  });
}

/** A motion approval must be admitted by the reader; anything else is only checked structurally. */
function gate(candidate: string, preview: Preview, row: JsonRecord, admits: boolean) {
  if (admits) return { admitted: true, result: assertNativeMotionReviewBundle(candidate, preview.packet) };
  const verdict = validateProducerReview(row.review, "plan").verdict;
  reviewIdentity(row.reviewer); reviewCoverage(row.coverage); reviewEvidence(row.evidence); readInspection(row.inspection);
  readApprovedContent(row.approvedContent, verdict); stringValue(row.assessment, "assessment", 4000);
  const observed = readCutPreviewObject(preview.path);
  if (observed.sha256 !== preview.sha256) throw new Error("Stale review inputs: the moving-preview record changed");
  return { admitted: false, result: null };
}

/** Re-read the published pass so a failure names the record that is now on disk. */
function admitPublished(file: string, preview: Preview) {
  try { return assertNativeMotionReviewBundle(file, preview.packet); } catch (error) {
    throw new Error(`Record ${file} was published but its re-read admission failed: ${String(error)}`);
  }
}

function outcome(verdict: string, admitted: boolean): { status: string | null; nextStep: string } {
  if (admitted) return { status: null, nextStep: "native_export.py <project> <new-attempt> --preview-reviews <this record>" };
  if (verdict === "pass") {
    return { status: "recorded-motion-review-picture-only", nextStep: "This pass approves what was looked at but not motion: "
      + "full rendering needs normal-speed motion playback of every window, recorded as typed motion-playback entries. "
      + "Obtain a playback review, or continue on the labeled review-draft route." };
  }
  return { status: `recorded-motion-review-${verdict === "block" ? "blocked" : "requires-revision"}`,
    nextStep: "Repair every material issue in one consolidated revision, rebuild, and obtain a fresh preview review." };
}

/** Bind a critic's observations to the exact preview; refuse stale, incomplete, inconsistent or unbacked input. */
export function submitNativeMotionReview(paths: ReviewSubmissionPaths) {
  const timer = stopwatch(), packet = readRolePacket(paths.packet, "motion-critic");
  assertPacketCurrent(packet);
  const output = canonicalOutput(paths.output, "Motion review record", packet.subject), preview = readPreview(packet);
  timer.mark("packetMs");
  const observations = readObservations({ file: paths.observations, kind: "native-motion-review-observations", packet,
    stage: "plan", clock: preview.clock, framesRequired: true });
  const evidence = bindEvidence(observations, packet, engineRoots(packet));
  const inspection = checkedInspection(observations, packet, evidence, preview), verdict = observations.review.verdict;
  const blocks = recordBlocks(observations, packet, inspection, { targets: preview.clips, fps: preview.clock.fps });
  const admits = verdict === "pass" && inspection.approves.includes("motion"), retained = admits ? retainedRows(packet) : [];
  const row = { reviewer: observations.reviewer, coverage: observations.coverage, evidence, inspection, ...blocks,
    review: observations.review, units: reviewedUnits(preview), preview: { path: preview.path, sha256: preview.sha256 },
    assessment: stringValue(observations.value.assessment, "assessment", 4000) };
  recordSubmission(packet, blocks.submission, row);
  timer.mark("observationsMs");
  const published = publishValidatedJson(output, { schemaVersion: 1, reviews: [...retained, row] },
    candidate => gate(candidate, preview, row, admits));
  const admission = published.gate.admitted ? admitPublished(published.path, preview) : null;
  timer.mark("publishMs");
  const next = outcome(verdict, Boolean(admission));
  return { status: admission ? admission.status : next.status, verdict, record: { path: published.path, sha256: published.sha256 },
    admitsFullRendering: Boolean(admission), units: row.units, retainedRows: retained.length,
    inspection: typedEvidence(inspection, preview.clips, observations.reviewer), approvedContent: blocks.approvedContent,
    submission: blocks.submission, independence: "reviewer-declared-not-authenticated",
    canonicalized: canonicalizedInputs(paths, [packet.path, observations.file.path, output]),
    timings: timer.report(), reviewSpan: reviewSpan(packet),
    nextStep: admission ? next.nextStep.replace("<this record>", published.path) : next.nextStep };
}
