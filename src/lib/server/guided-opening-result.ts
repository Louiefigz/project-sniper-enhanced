import path from "node:path";
import { parseOpeningMediaCompletion, parseOpeningMediaReadback } from "@/lib/producer/contracts/guided-opening-result-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readStoppedOpeningProcess, type HeldOpeningClaim } from "./guided-opening-process";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { canonicalJsonSha256 } from "./auto-edit-hash";

/** Receipt-byte evidence for the separate current-media verifier.
 * This type deliberately retains false source/media observation flags.
 */
export type HeldOpeningResult = ReturnType<typeof readHeldOpeningResult>;

/** Source-color transport must not borrow legacy result/readback schemas while its separate schema2 proof reader is absent. */
export function assertSupportedOpeningMediaProcess(process: ReturnType<typeof readStoppedOpeningProcess>): void {
  if (process.receipt.schemaVersion !== 1 && process.receipt.schemaVersion !== 2 || process.sourceColor != null) {
    throw new Error("Source-color opening media requires schema2 result and readback validation, which is not implemented");
  }
}

/** Read only exact completion-bound receipt bytes. No movie/source/graphics freshness is asserted by this function. */
export function readHeldOpeningResult(held: HeldOpeningClaim) {
  const process = readStoppedOpeningProcess(held);
  assertSupportedOpeningMediaProcess(process);
  if (process.receipt.status !== "complete") throw new Error("Opening media process did not complete successfully");
  const completion = parseOpeningMediaCompletion(String(process.receipt.stdout));
  const expectedPath = path.join(held.claim.outputRoot, "media-result.json");
  if (completion.executionId !== held.claim.executionId || completion.inputSha256 !== held.claim.inputSha256
      || completion.executionInputHash !== held.claim.executionInputHash || completion.executionClaimSha256 !== held.claimSha256
      || completion.receiptPath !== expectedPath) throw new Error("Opening completion does not name its actual held execution");
  assertOpeningFailureAbsent(path.join(held.claim.outputRoot, "media-failed.json"));
  assertOpeningFailureAbsent(path.join(held.claim.outputRoot, "audio/audio-failed.json"));
  const record = readCutPreviewObject(expectedPath), { receiptHash, ...body } = record.value;
  if (record.sha256 !== completion.receiptSha256 || receiptHash !== completion.receiptHash
      || canonicalJsonSha256(body) !== receiptHash) throw new Error("Opening result bytes differ from the actual worker completion");
  return { process, completion, record, observationScope: "actual-completion-and-receipt-bytes-only" as const,
    sourceBytesObserved: false as const, mediaBytesObserved: false as const, mediaSelected: false as const };
}

/** Match a just-returned owned read-only child, never a result chosen from a directory. */
export function assertOpeningReadbackIdentity(stdout: string, input: { held: HeldOpeningClaim; selected: ReturnType<typeof readHeldOpeningResult> }) {
  assertSupportedOpeningMediaProcess(input.selected.process);
  const value = parseOpeningMediaReadback(stdout), { held, selected } = input;
  if (value.executionId !== held.claim.executionId || value.inputSha256 !== held.claim.inputSha256
      || value.executionInputHash !== held.claim.executionInputHash || value.claimSha256 !== held.claimSha256
      || value.receiptPath !== selected.completion.receiptPath || value.receiptSha256 !== selected.completion.receiptSha256
      || value.receiptHash !== selected.completion.receiptHash) throw new Error("Opening read-only result does not bind this actual completion");
  return value;
}

/** Reobserve the same held bytes at a later boundary. Still no media-file or source-freshness claim. */
export function assertHeldOpeningResultUnchanged(held: HeldOpeningClaim, selected: ReturnType<typeof readHeldOpeningResult>): void {
  const next = readHeldOpeningResult(held);
  if (next.process.receiptSha256 !== selected.process.receiptSha256
      || next.record.sha256 !== selected.record.sha256 || canonicalJsonSha256(next.completion) !== canonicalJsonSha256(selected.completion)) {
    throw new Error("Opening actual process/result changed across observation");
  }
}

/** Receipt authority comes from the held actual completion, never from a fresh directory hash. */
export function openingReadbackReceiptArguments(selected: ReturnType<typeof readHeldOpeningResult>): string[] {
  assertSupportedOpeningMediaProcess(selected.process);
  return ["--receipt-sha256", selected.completion.receiptSha256,
    "--receipt-hash", selected.completion.receiptHash];
}
