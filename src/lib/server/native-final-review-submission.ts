/** Typed submission of an independent critic's review of a checked native Short MP4. */
import { exactKeys, objectValue, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { assertNativeFinalReview, checkedExport, NATIVE_FINAL_REVIEW_SCOPE } from "./native-final-review";
import type { NativePrebuildReviewBinding } from "./native-short-prebuild-review";
import { assertPacketCurrent, canonicalOutput, frozenArtifact, publishValidatedJson, readRolePacket, reviewSpan,
  stopwatch, type RolePacket } from "./native-review-packet";
import { assertClaimsObserved, bindEvidence, bindInspection, frameClock, frameInteger, readObservations, recordBlocks,
  recordSubmission, type FrameClock, type Observations } from "./native-review-observations";
import { assertApprovals, assertBoundToTargets, assertFrameSeen, assertGapsStated, canonicalizedInputs, type Inspection,
  type ReviewSubmissionPaths, type ReviewTarget } from "./native-review-submission-shared";

interface Program { target: ReviewTarget; clock: FrameClock }

function exportBindings(packet: RolePacket) {
  const exported = objectValue(packet.subject.export, "role packet export");
  const [delivery, video] = ["delivery", "video"].map(key => {
    const row = objectValue(exported[key], `role packet ${key}`), file = stringValue(row.path, `${key} path`, 4096);
    return { path: file, sha256: frozenArtifact(packet, file).sha256 };
  });
  return { delivery, video };
}

function frameNote(value: unknown, label: string, clock: FrameClock): JsonRecord {
  const row = objectValue(value, label);
  exactKeys(row, ["frame", "note"], ["frame", "note"], label);
  frameInteger(row.frame, `${label}.frame`, clock);
  stringValue(row.note, `${label}.note`, 1000);
  return row;
}

/** Frame-numbered notes of what was seen; each lies where someone looked at the exact MP4. */
function assertFrameNotes(observations: Observations, program: Program, inspection: Inspection): void {
  const notes = observations.value.frameNotes;
  if (!Array.isArray(notes) || !notes.length) throw new Error("frameNotes needs frame-numbered notes of what was actually seen");
  notes.forEach((value, index) => {
    const label = `frameNotes[${index}]`, row = frameNote(value, label, program.clock);
    assertFrameSeen(inspection, program.target, row.frame as number, label);
  });
}

/** One note per program event, each at a frame that was actually looked at (stills or playback). */
function assertEventNotes(observations: Observations, packet: RolePacket, program: Program, inspection: Inspection): void {
  const expected = packet.subject.events, notes = observations.value.events, clock = program.clock;
  if (!Array.isArray(expected) || !Array.isArray(notes) || notes.length !== expected.length) {
    throw new Error(`events must note every one of the packet's ${Array.isArray(expected) ? expected.length : 0} program events in order`);
  }
  notes.forEach((value, index) => {
    const row = frameNote(value, `events[${index}]`, clock), frame = objectValue(expected[index], "packet event").frame;
    if (row.frame !== frame) throw new Error(`events[${index}] must note frame ${String(frame)}`);
    assertFrameSeen(inspection, program.target, frame as number, `events[${index}]`);
  });
}

/** Bind the typed entries, then refuse stale bytes, unbacked approvals, unseen notes and located claims, and unstated gaps. */
function checkedInspection(observations: Observations, packet: RolePacket, evidence: NativePrebuildReviewBinding[], program: Program) {
  const inspection = bindInspection(observations, packet, evidence), targets = [program.target];
  assertBoundToTargets(inspection, targets);
  assertApprovals(inspection, targets, String(observations.review.verdict));
  assertFrameNotes(observations, program, inspection);
  assertEventNotes(observations, packet, program, inspection);
  assertClaimsObserved(observations, inspection, targets);
  assertGapsStated(inspection, targets, observations.limitations);
  return inspection;
}

function nextStep(gate: ReturnType<typeof assertNativeFinalReview>): string {
  const surfaced = gate.approvedContent?.proposedChanges.length ? ` Surface the proposed-change findings `
    + `(${gate.approvedContent.proposedChanges.join(", ")}) to the operator; they need no second approval round.` : "";
  if (gate.editorialFinal === "approved") {
    return "Hand off the checked MP4 and the matching live Studio project as the editorially reviewed final (declared, "
      + `not authenticated); the operator's own approval remains theirs.${surfaced}`;
  }
  if (gate.verdict === "pass") {
    return `Not an editorially approved final (missing: ${gate.missing.join("; ")}). Hand it off only as a checked review `
      + `MP4 with those gaps stated, or obtain a review that performs them.${surfaced}`;
  }
  return "Repair every material issue in one consolidated revision; the checked MP4 stays a review draft until then.";
}

/** Bind a critic's typed observations to the exact checked MP4 and rendered plan. */
export function submitNativeFinalReview(paths: ReviewSubmissionPaths) {
  const timer = stopwatch(), packet = readRolePacket(paths.packet, "final-critic");
  assertPacketCurrent(packet);
  const output = canonicalOutput(paths.output, "Final review record", packet.subject), bound = exportBindings(packet);
  const checked = checkedExport(bound.delivery, bound.video), clock = frameClock(packet.subject.frameRate, packet.subject.totalFrames);
  if (clock.totalFrames !== checked.totalFrames) throw new Error("Role packet frame count differs from the rendered project");
  const program = { target: { ...bound.video, startFrame: 0, endFrameExclusive: clock.totalFrames }, clock };
  timer.mark("packetMs");
  const observations = readObservations({ file: paths.observations, kind: "native-final-review-observations", packet,
    stage: "rendered", clock, framesRequired: true });
  const evidence = bindEvidence(observations, packet), inspection = checkedInspection(observations, packet, evidence, program);
  const blocks = recordBlocks(observations, packet, inspection, { targets: [program.target], fps: clock.fps });
  const record = { schemaVersion: 2, scope: NATIVE_FINAL_REVIEW_SCOPE, export: bound, planHash: checked.planHash,
    reviewer: observations.reviewer, coverage: observations.coverage, evidence, review: observations.review, inspection,
    ...blocks, assessment: stringValue(observations.value.assessment, "assessment", 4000) };
  recordSubmission(packet, blocks.submission, record);
  timer.mark("observationsMs");
  const published = publishValidatedJson(output, record, candidate => assertNativeFinalReview(candidate));
  timer.mark("publishMs");
  return { ...published.gate, record: { path: published.path, sha256: published.sha256 },
    canonicalized: canonicalizedInputs(paths, [packet.path, observations.file.path, output]),
    timings: timer.report(), reviewSpan: reviewSpan(packet), nextStep: nextStep(published.gate) };
}
