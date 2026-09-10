import path from "node:path";
import { existsSync } from "node:fs";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseRawTreatmentSubmissionV1, type RawTreatmentSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { exactKeys, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedCutV2 } from "./guided-cut-v2";
import { readGuidedObject, strictGuidedTimestamp, writeGuidedObject, type guidedOperation } from "./guided-cut-v2-store";
import { createHumanCutIndex, humanCutDirectory, observeHumanCutJob } from "./human-cut-acceptance-store";
import { producerAuthorityPaths, writeAuthorityObjectSync } from "./producer-authority-files";
import { readTreatmentAdmissionLineage, readTreatmentRevisionReservation } from "./guided-treatment-revision-store";

export type AcceptedGuidedCut = ReturnType<typeof readGuidedCutV2>;
/** Fixed reader reference for in-process protocol tests; not a request-selectable authority. */
export const rawTreatmentAdmissionReads = { cut: readGuidedCutV2 };
const CLOCK_SCOPE = "first-post-cut-request-includes-compilation-retries-and-clarification";

/** Original raw input, not a synthetic compiled clause or inferred approval. */
export function readRawTreatmentClock(cut: Pick<AcceptedGuidedCut, "job" | "fact" | "pointer" | "activation">, expected?: string) {
  const dir = cut.job.ctx.dir, index = readCutPreviewObject(path.join(dir, "guided-v2-operations", `generation-${cut.pointer.cutDecisionHash}.json`)).value;
  exactKeys(index, ["clockHash"], ["clockHash"], "generation origin index");
  const hash = sha256(index.clockHash, "clockHash"), value = readGuidedObject(dir, hash);
  const keys = ["schemaVersion", "kind", "runId", "cutDecisionHash", "firstRequestHash", "firstIntakeHash", "startedAt", "scope"];
  exactKeys(value, keys, keys, "raw generation origin");
  if (value.schemaVersion !== 3 || value.kind !== "guided-raw-generation-clock-origin" || value.runId !== cut.fact.runId
      || value.cutDecisionHash !== cut.pointer.cutDecisionHash || value.scope !== CLOCK_SCOPE || (expected && expected !== hash)
      || strictGuidedTimestamp(value.startedAt) < String(cut.activation.recordedAt)) throw new Error("Raw treatment must preserve its exact original generation clock; no typed/raw clock migration");
  const request = readCutPreviewObject(path.join(dir, ".sniper-authority-v1", "objects", "requests", `${sha256(value.firstRequestHash, "firstRequestHash")}.json`));
  const submission = parseRawTreatmentSubmissionV1(request.value);
  const intake = readCutPreviewObject(path.join(dir, "guided-v2-operations", submission.idempotencyKey, "submission.json"));
  if (request.sha256 !== value.firstRequestHash || canonicalJsonSha256(submission) !== value.firstRequestHash
      || intake.sha256 !== sha256(value.firstIntakeHash, "firstIntakeHash") || intake.value.receivedAt !== value.startedAt
      || intake.value.submissionHash !== value.firstRequestHash || canonicalJsonSha256(intake.value.submission) !== value.firstRequestHash
      || submission.cutDecisionHash !== cut.pointer.cutDecisionHash || submission.parentRevisionHash !== cut.pointer.pictureLockedRevisionHash) {
    throw new Error("Raw generation clock lost its exact original request lineage");
  }
  return { hash, value, submission };
}

export function ensureRawTreatmentClock(cut: AcceptedGuidedCut, submission: RawTreatmentSubmissionV1, operation: ReturnType<typeof guidedOperation>) {
  const dir = cut.job.ctx.dir, root = humanCutDirectory(dir, "guided-v2-operations");
  const file = path.join(root, `generation-${cut.pointer.cutDecisionHash}.json`);
  const requestHash = writeAuthorityObjectSync(producerAuthorityPaths(dir).objects.requests, submission).hash;
  if (!existsSync(file)) {
    const intake = readCutPreviewObject(path.join(operation.directory, "submission.json"));
    const clockHash = writeGuidedObject(dir, { schemaVersion: 3, kind: "guided-raw-generation-clock-origin",
      runId: cut.fact.runId, cutDecisionHash: cut.pointer.cutDecisionHash, firstRequestHash: requestHash,
      firstIntakeHash: intake.sha256, startedAt: operation.record.receivedAt, scope: CLOCK_SCOPE });
    createHumanCutIndex(file, { clockHash });
  }
  const clock = readRawTreatmentClock(cut);
  if (canonicalJsonSha256(clock.submission) !== requestHash) throw new Error("An earlier raw request exists; a different brief requires explicit future revision, not silent replacement");
  return clock;
}

/** Validate raw-admission proof and before-journal closure without writing or compiling. */
export function readRawTreatmentAdmission(dir: string, options: { pendingRevisionObservation?: true } = {}) {
  const cut = rawTreatmentAdmissionReads.cut(dir), hash = cut.pointer.treatmentAdmissionHash;
  if (cut.job.status !== "treatment_admitted" || !hash) throw new Error("No raw treatment request has been admitted");
  const { clock, nodes } = readTreatmentAdmissionLineage(cut, hash), { admission, submission } = nodes[0];
  if (!options.pendingRevisionObservation && readTreatmentRevisionReservation(dir, hash)) {
    throw new Error("Pending treatment revision blocks old-brief execution; explicit reconcile-revision is required");
  }
  if (observeHumanCutJob(dir).sha256 !== cut.sha256) throw new Error("Raw treatment journal changed during observation");
  return { ...cut, admission, submission, clock, lineage: nodes, generationStartedAt: String(clock.value.startedAt) };
}
