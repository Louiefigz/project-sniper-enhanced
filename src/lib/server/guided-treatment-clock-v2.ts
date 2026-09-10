import path from "node:path";
import { existsSync } from "node:fs";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseEditRequestV1, type EditRequestV1 } from "@/lib/producer/contracts/edit-request";
import { parseTreatmentIntakeV1 } from "@/lib/producer/contracts/treatment-handoff-v1";
import { exactKeys, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { createHumanCutIndex, humanCutDirectory } from "./human-cut-acceptance-store";
import { producerAuthorityPaths, writeAuthorityObjectSync } from "./producer-authority-files";
import { readGuidedObject, strictGuidedTimestamp, writeGuidedObject, type guidedOperation } from "./guided-cut-v2-store";
import type { readGuidedCutV2 } from "./guided-cut-v2";

type AcceptedCut = ReturnType<typeof readGuidedCutV2>;
const SCOPE = "first-post-cut-request-includes-compilation-retries-and-clarification";

/** Read the fixed origin plus its original authorized request, not a caller-selected replacement clock. */
export function readTreatmentClockV2(cut: AcceptedCut, expected?: { hash: string; noLaterThan: string }) {
  const dir = cut.job.ctx.dir, file = path.join(dir, "guided-v2-operations", `generation-${cut.pointer.cutDecisionHash}.json`);
  const pointer = readCutPreviewObject(file).value;
  exactKeys(pointer, ["clockHash"], ["clockHash"], "generation clock pointer");
  const hash = sha256(pointer.clockHash, "clockHash"), value = readGuidedObject(dir, hash);
  const keys = ["schemaVersion", "kind", "runId", "cutDecisionHash", "firstRequestHash", "firstIntakeHash", "startedAt", "scope"];
  exactKeys(value, keys, keys, "generation clock");
  const startedAt = strictGuidedTimestamp(value.startedAt);
  if (value.schemaVersion !== 2 || value.kind !== "guided-generation-clock-origin" || value.runId !== cut.fact.runId
      || value.cutDecisionHash !== cut.pointer.cutDecisionHash || value.scope !== SCOPE
      || startedAt < String(cut.activation.recordedAt) || (expected && (hash !== expected.hash || startedAt > expected.noLaterThan))) {
    throw new Error("V2 generation clock origin changed");
  }
  const original = readCutPreviewObject(path.join(dir, ".sniper-authority-v1", "objects", "requests", `${sha256(value.firstRequestHash, "firstRequestHash")}.json`));
  const request = parseEditRequestV1(original.value);
  const intake = readCutPreviewObject(path.join(dir, "guided-v2-operations", request.idempotencyKey, "submission.json"));
  const submission = parseTreatmentIntakeV1(intake.value.submission);
  if (original.sha256 !== value.firstRequestHash || canonicalJsonSha256(request) !== value.firstRequestHash
      || request.parentRevisionHash !== cut.pointer.pictureLockedRevisionHash || intake.sha256 !== sha256(value.firstIntakeHash, "firstIntakeHash")
      || intake.value.receivedAt !== startedAt || intake.value.submissionHash !== canonicalJsonSha256(submission)
      || canonicalJsonSha256(submission.request) !== value.firstRequestHash || submission.cutDecisionHash !== cut.pointer.cutDecisionHash) {
    throw new Error("V2 generation origin lost its original authorized intake lineage");
  }
  return { hash, value, request };
}

/** Every raw intake is stored; the first confirmed request starts one clock even if compilation blocks. */
export function ensureTreatmentClockV2(cut: AcceptedCut, request: EditRequestV1, operation: ReturnType<typeof guidedOperation>) {
  const dir = cut.job.ctx.dir, root = humanCutDirectory(dir, "guided-v2-operations");
  const file = path.join(root, `generation-${cut.pointer.cutDecisionHash}.json`);
  const requestHash = writeAuthorityObjectSync(producerAuthorityPaths(dir).objects.requests, request).hash;
  if (!existsSync(file)) {
    const intake = readCutPreviewObject(path.join(operation.directory, "submission.json"));
    const clockHash = writeGuidedObject(dir, { schemaVersion: 2, kind: "guided-generation-clock-origin",
      runId: cut.fact.runId, cutDecisionHash: cut.pointer.cutDecisionHash, firstRequestHash: requestHash,
      firstIntakeHash: intake.sha256, startedAt: operation.record.receivedAt, scope: SCOPE });
    createHumanCutIndex(file, { clockHash });
  }
  return readTreatmentClockV2(cut, { hash: sha256(readCutPreviewObject(file).value.clockHash, "clockHash"), noLaterThan: operation.startedAt });
}

/** A corrected brief cannot erase earlier blocked clauses; explicit supersession retains their identity. */
export function assertTreatmentRequestLineage(original: EditRequestV1, current: EditRequestV1): void {
  for (const prior of original.clauses) {
    const retained = current.clauses.filter((clause) => clause.clauseId === prior.clauseId && clause.text === prior.text);
    const superseding = current.clauses.filter((clause) => clause.supersedesClauseId === prior.clauseId && clause.clauseId !== prior.clauseId);
    if (retained.length + superseding.length !== 1) throw new Error("Earlier treatment clauses must remain or have one explicit superseding clause");
  }
}
