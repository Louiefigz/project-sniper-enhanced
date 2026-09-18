import path from "node:path";
import { lstatSync } from "node:fs";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseContinueApprovedOpening } from "@/lib/producer/contracts/guided-body-v1";
import { objectValue, exactKeys, sha256 } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { createOpeningRecord } from "./guided-opening-process-activation";
import { readGuidedObject, writeGuidedObject, strictGuidedTimestamp, type guidedOperation } from "./guided-cut-v2-store";
import type { holdGuidedBodyInputUnderLease } from "./guided-body-authority";
import type { readSelectedOpeningMedia } from "./guided-opening-selection";
import { openingSelectionVersion } from "./guided-opening-selection";
import { assertBodyHeldSourceColorMetadata } from "./guided-body-authority";
import { parseBodySourceColorReplayReferences } from "@/lib/producer/contracts/guided-body-source-color-replay-v2";

export type BodyOperation = ReturnType<typeof guidedOperation>;
export type HeldBodyInput = Awaited<ReturnType<typeof holdGuidedBodyInputUnderLease>>;
export type BodySelection = ReturnType<typeof readSelectedOpeningMedia>;

/** Preserve ORIGINAL opening input and result identities; never rewrite their execution ID for body work. */
export function bodyHeldDocument(held: HeldBodyInput, selected: BodySelection) {
  const version = openingSelectionVersion(selected);
  if (held.schemaVersion !== version) throw new Error("Body held input and original opening versions differ");
  if (version === 2) assertBodyHeldSourceColorMetadata(held);
  const { assertUnchanged: _guard, ...input } = held; void _guard;
  const opening = selected.held;
  if (selected.selectionHash !== held.selectionHash || selected.observed.sha256 !== held.journalHash) throw new Error("Body held opening selection changed");
  return { schemaVersion: version, kind: "guided-body-held-input", input,
    opening: { claimPath: opening.claimPath, claimSha256: opening.claimSha256,
      inputPath: opening.claim.inputPath, inputSha256: opening.claim.inputSha256,
      executionInputHash: opening.claim.executionInputHash, outputRoot: opening.claim.outputRoot,
      resultPath: path.join(opening.claim.outputRoot, "media-result.json"), resultSha256: selected.receiptSha256 } };
}

/** Store exact private bytes and their separate CAS object before the journal selects the claim. */
export function writeBodyObject(dir: string, operation: BodyOperation, name: string, value: unknown): string {
  if (!["held-input.json", "budget-admission.json", "budget-precommit.json", "claim.json"].includes(name)) throw new Error("Unsupported body object role");
  const hash = writeGuidedObject(dir, value), record = createOpeningRecord(path.join(operation.execution, name), objectValue(value, name));
  if (record.sha256 !== hash) throw new Error("Body private and held object bytes differ");
  return hash;
}

export function readBodyObject(dir: string, execution: string, name: string, hash: string) {
  const object = readGuidedObject(dir, hash), file = readCutPreviewObject(path.join(execution, name));
  if (file.sha256 !== hash || canonicalJsonSha256(file.value) !== hash) throw new Error(`Body private ${name} differs from its held object`);
  return object;
}

/** A retained intake is not permission to make another execution. Missing/corrupt/partial attempts never auto-retry. */
export function assertFreshBodyRequest(dir: string, submission: ReturnType<typeof parseContinueApprovedOpening>): void {
  const file = path.join(dir, "guided-v2-operations", submission.idempotencyKey, "submission.json");
  try { lstatSync(file); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  const value = readCutPreviewObject(file).value;
  const prior = parseContinueApprovedOpening(value.submission);
  if (canonicalJsonSha256(prior) !== canonicalJsonSha256(submission)) throw new Error("Body idempotency key conflicts with its retained request");
  throw new Error("Body request has a retained incomplete admission; no fresh execution or automatic retry is allowed");
}

/** Structural readback only. Its separate journal-bound hash and approval lineage are mandatory. */
export function parseBodyHeldDocument(value: unknown) {
  const row = objectValue(value, "held body document"), input = objectValue(row.input, "held body input");
  exactKeys(row, ["schemaVersion", "kind", "input", "opening"], ["schemaVersion", "kind", "input", "opening"], "held body document");
  const keys = ["schemaVersion", "scope", "submission", "journalHash", "approvalHash", "selectionHash", "readinessHash", "draftRevisionHash",
    "authority", "bindings", "origin", "references", "verification", "executable", "bodyReadiness", "bodyGenerated", "deliveryApproved"];
  if (row.schemaVersion === 2) keys.push("sourceColorReplay");
  exactKeys(input, keys, keys, "held body input");
  if ((row.schemaVersion !== 1 && row.schemaVersion !== 2) || row.kind !== "guided-body-held-input" || input.schemaVersion !== row.schemaVersion
      || input.scope !== "held-body-input-not-launch-body-readiness-or-delivery-approval" || input.executable !== false
      || input.bodyReadiness !== "not-qualified" || input.bodyGenerated !== false || input.deliveryApproved !== false) throw new Error("Body input is not non-executable held evidence");
  const submission = parseContinueApprovedOpening(input.submission), origin = objectValue(input.origin, "body origin");
  exactKeys(origin, ["clockHash", "startedAt"], ["clockHash", "startedAt"], "body origin");
  sha256(origin.clockHash, "body clockHash"); strictGuidedTimestamp(origin.startedAt);
  for (const key of ["journalHash", "approvalHash", "selectionHash", "readinessHash", "draftRevisionHash"]) sha256(input[key], key);
  const opening = objectValue(row.opening, "body original opening");
  const openingKeys = ["claimPath", "claimSha256", "inputPath", "inputSha256", "executionInputHash", "outputRoot", "resultPath", "resultSha256"];
  exactKeys(opening, openingKeys, openingKeys, "body original opening");
  for (const key of ["claimPath", "inputPath", "outputRoot", "resultPath"]) openingAbsolutePath(opening[key]);
  for (const key of ["claimSha256", "inputSha256", "executionInputHash", "resultSha256"]) sha256(opening[key], key);
  if (row.schemaVersion === 2) {
    const replay = parseBodySourceColorReplayReferences(input.sourceColorReplay);
    if (replay.opening.selectionHash !== input.selectionHash || replay.opening.inputSha256 !== opening.inputSha256
        || replay.opening.executionInputHash !== opening.executionInputHash || replay.opening.mediaResultSha256 !== opening.resultSha256) {
      throw new Error("Body source-color replay differs from its held opening");
    }
  }
  return { row, input, opening, submission, origin };
}
