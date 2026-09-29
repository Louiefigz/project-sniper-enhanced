/** Typed submission of an independent full-plan prebuild review, and its binding into a new plan file. */
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { atomicCreateFileSync } from "./atomic-file";
import { assertNativeShortPrebuildReview, nativeShortPrebuildPlanHash, planInspection,
  readNativeShortPrebuildRecord } from "./native-short-prebuild-review";
import type { NativeShortProjectInput } from "./native-short-project";
import { assertPacketCurrent, canonicalInput, canonicalOutput, frozenArtifact, publishValidatedJson, readRolePacket,
  reviewSpan, stopwatch, type RolePacket } from "./native-review-packet";
import { bindEvidence, bindInspection, frameClock, frameInteger, readObservations, recordBlocks, recordSubmission,
  type FrameClock, type Observations } from "./native-review-observations";
import { canonicalizedInputs, typedEvidence, type ReviewSubmissionPaths } from "./native-review-submission-shared";

interface Plan { path: string; sha256: string; value: NativeShortProjectInput; planHash: string; clock: FrameClock }
/** With shared evidence bound (role_packets.with_evidence_basis), each scene says whether it was inspected or rests on that evidence alone. */
const EVIDENCE_BASIS = ["inspected", "shared-evidence-only"];

function assertEvidenceBasis(row: JsonRecord, index: number, bound: boolean): void {
  if (!bound && row.evidenceBasis !== undefined) {
    throw new Error(`scenes[${index}].evidenceBasis names shared evidence, but this role packet binds none`);
  }
  if (bound && !EVIDENCE_BASIS.includes(row.evidenceBasis as string)) {
    throw new Error(`scenes[${index}].evidenceBasis is required with shared evidence bound: ${EVIDENCE_BASIS.join(" or ")}`);
  }
}

function readPlan(packet: RolePacket): Plan {
  const subject = objectValue(packet.subject.plan, "role packet plan"), file = stringValue(subject.path, "plan path", 4096);
  const observed = readCutPreviewObject(file);
  if (observed.sha256 !== frozenArtifact(packet, file).sha256) throw new Error("Stale review inputs: the plan changed");
  const value = observed.value as unknown as NativeShortProjectInput, planHash = nativeShortPrebuildPlanHash(value);
  if (planHash !== subject.planHash) throw new Error("Role packet plan digest disagrees with the plan's authored fields");
  const canvas = objectValue(value.canvas, "plan canvas");
  return { path: file, sha256: observed.sha256, value, planHash, clock: frameClock(canvas.frameRate, canvas.totalFrames) };
}

function assertSceneNotes(observations: Observations, plan: Plan, bound: boolean): void {
  const scenes = objectValue(plan.value.strategy, "plan strategy").scenes, notes = observations.value.scenes;
  if (!Array.isArray(scenes) || !Array.isArray(notes) || notes.length !== scenes.length) {
    throw new Error(`scenes must note every one of the plan's ${Array.isArray(scenes) ? scenes.length : 0} scenes in order`);
  }
  notes.forEach((value, index) => {
    const row = objectValue(value, `scenes[${index}]`), scene = objectValue(scenes[index], "plan scene");
    exactKeys(row, ["index", "startFrame", "endFrame", "note", "evidenceBasis"], ["index", "startFrame", "endFrame", "note"], `scenes[${index}]`);
    assertEvidenceBasis(row, index, bound);
    if (row.index !== index || frameInteger(row.startFrame, `scenes[${index}].startFrame`, plan.clock) !== scene.startFrame
        || frameInteger(row.endFrame, `scenes[${index}].endFrame`, plan.clock, true) !== scene.endFrame) {
      throw new Error(`scenes[${index}] must be scene ${index}, frames ${String(scene.startFrame)}–${String(scene.endFrame)}`);
    }
    stringValue(row.note, `scenes[${index}].note`, 2000);
  });
}

/** A pass must be admitted by the build gate; any other verdict must still read as a complete current record. */
function gate(candidate: string, digest: string, plan: Plan, record: JsonRecord): boolean {
  const bound = { ...plan.value, prebuildReview: { path: candidate, sha256: digest } };
  if (validateProducerReview(record.review, "plan").verdict === "pass") {
    assertNativeShortPrebuildReview(bound);
    return true;
  }
  readNativeShortPrebuildRecord(bound);
  return false;
}

/** Bind a critic's full-plan judgment to the exact authored plan digest. */
export function submitNativePrebuildReview(paths: ReviewSubmissionPaths) {
  const timer = stopwatch(), packet = readRolePacket(paths.packet, "plan-critic");
  assertPacketCurrent(packet);
  const output = canonicalOutput(paths.output, "Prebuild review record", packet.subject), plan = readPlan(packet);
  timer.mark("packetMs");
  const observations = readObservations({ file: paths.observations, kind: "native-plan-review-observations", packet,
    stage: "plan", clock: plan.clock, framesRequired: false });
  assertSceneNotes(observations, plan, packet.sharedEvidence !== null);
  const evidence = bindEvidence(observations, packet), inspection = planInspection(bindInspection(observations, packet, evidence));
  const blocks = recordBlocks(observations, packet, inspection, { targets: [], fps: plan.clock.fps });
  const record = { schemaVersion: 2, scope: "native-short-full-plan", planHash: plan.planHash, reviewer: observations.reviewer,
    coverage: observations.coverage, evidence, inspection, ...blocks, review: observations.review };
  recordSubmission(packet, blocks.submission, record);
  timer.mark("observationsMs");
  const published = publishValidatedJson(output, record, (candidate, digest) => gate(candidate, digest, plan, record));
  timer.mark("publishMs");
  return { status: published.gate ? "recorded-independent-plan-pass"
    : `recorded-plan-review-${observations.review.verdict === "block" ? "blocked" : "requires-revision"}`,
    verdict: observations.review.verdict, record: { path: published.path, sha256: published.sha256 }, planHash: plan.planHash,
    admitsBuild: published.gate, inspection: typedEvidence(inspection, [], observations.reviewer), approvesRenderedMedia: false,
    approvedContent: blocks.approvedContent, submission: blocks.submission,
    independence: "reviewer-declared-not-authenticated",
    canonicalized: canonicalizedInputs(paths, [packet.path, observations.file.path, output]),
    timings: timer.report(), reviewSpan: reviewSpan(packet),
    nextStep: published.gate ? `native-review.ts bind-prebuild ${plan.path} ${published.path} <new-plan.json>`
      : "Revise the plan for every material issue in one consolidated pass, then obtain a fresh plan review." };
}

/** Write a new plan file carrying a verified current prebuildReview binding; the plan digest is unchanged. */
export function bindNativePrebuildReview(planFile: string, recordFile: string, newPlanFile: string) {
  const source = canonicalInput(planFile, "Plan"), record = canonicalInput(recordFile, "Prebuild review record");
  const output = canonicalOutput(newPlanFile, "New plan");
  const plan = readCutPreviewObject(source).value as unknown as NativeShortProjectInput;
  const bound = { ...plan, prebuildReview: { path: record, sha256: readCutPreviewObject(record).sha256 } };
  assertNativeShortPrebuildReview(bound);
  atomicCreateFileSync(output, `${JSON.stringify(bound, null, 2)}\n`);
  const written = readCutPreviewObject(output), check = written.value as unknown as NativeShortProjectInput;
  try {
    assertNativeShortPrebuildReview(check);
    if (nativeShortPrebuildPlanHash(check) !== nativeShortPrebuildPlanHash(plan)) throw new Error("Bound plan digest changed");
  } catch (error) {
    throw new Error(`New plan ${output} was written but its re-read verification failed: ${String(error)}`);
  }
  return { status: "prebuild-review-bound", plan: { path: output, sha256: written.sha256 },
    planHash: nativeShortPrebuildPlanHash(check), prebuildReview: bound.prebuildReview,
    nextStep: `native-short.ts build ${output} <new-project>` };
}
