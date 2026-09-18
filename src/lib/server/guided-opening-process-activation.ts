import path from "node:path";
import { lstatSync } from "node:fs";
import { exactKeys, sha256, uuid } from "@/lib/producer/contracts/validation";
import { readCutPreviewObject, assertCutPreviewDirectory } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { atomicCreateFileSync } from "./atomic-file";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import type { observeHumanCutJob } from "./human-cut-acceptance-store";

export interface HeldOpeningRecord { path: string; sha256: string; value: Record<string, unknown> }

/** Hold exact bytes BEFORE publication; later disk reads may only compare to that authority. */
export function createOpeningRecord(file: string, value: Record<string, unknown>): HeldOpeningRecord {
  const held = { path: file, sha256: canonicalJsonSha256(value), value };
  assertCutPreviewDirectory(path.dirname(file));
  atomicCreateFileSync(file, canonicalJson(value)); assertOpeningRecord(held); return held;
}
export function assertOpeningRecord(held: HeldOpeningRecord): void {
  const file = readCutPreviewObject(held.path);
  if (file.sha256 !== held.sha256 || canonicalJsonSha256(file.value) !== canonicalJsonSha256(held.value)) throw new Error("Opening held exact record bytes changed");
}
export function assertOpeningFailureAbsent(file: string): void {
  try { lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Opening execution has a failure marker; success cannot be committed");
}

/** Actual owned-return hashes are separately journal-held, never inferred from mutually consistent sidecars. */
export function readOpeningProcessActivation(dir: string, current: ReturnType<typeof observeHumanCutJob>) {
  const hash = current.job.guidedHandoffV2?.openingProcessOutcomeHash;
  if (!hash) throw new Error("No durable actual opening process outcome is held; automatic recovery is unavailable");
  const row = readGuidedObject(dir, hash), keys = ["schemaVersion", "kind", "scope", "claimHash", "beforeJournalHash",
    "executionId", "inputSha256", "intentSha256", "outcomeSha256", "clockHash", "generationStartedAt", "createdAt"];
  exactKeys(row, keys, keys, "opening process activation"); uuid(row.executionId, "executionId");
  for (const key of ["claimHash", "beforeJournalHash", "inputSha256", "intentSha256", "outcomeSha256", "clockHash"]) sha256(row[key], key);
  const file = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${row.beforeJournalHash}.json`));
  const prior = { ...file, job: parseAutoEditJobRecord(file.value) };
  const { openingProcessOutcomeHash: _outcome, ...pointer } = current.job.guidedHandoffV2!; void _outcome;
  if (![1, 2].includes(Number(row.schemaVersion)) || typeof row.schemaVersion !== "number" || row.kind !== "guided-opening-process-activation"
      || row.scope !== "actual-owned-process-outcome-not-media-or-delivery-approval" || file.sha256 !== row.beforeJournalHash
      || prior.job.ctx.dir !== dir || prior.job.status !== "treatment_admitted" || current.job.status !== "treatment_admitted"
      || prior.job.guidedHandoffV2?.openingProcessOutcomeHash || !prior.job.guidedHandoffV2?.openingExecutionClaimHash
      || row.claimHash !== prior.job.guidedHandoffV2.openingExecutionClaimHash || prior.job.token !== current.job.token
      || prior.job.attempts !== current.job.attempts || prior.job.artifactToken !== current.job.artifactToken
      || canonicalJsonSha256(prior.job.ctx) !== canonicalJsonSha256(current.job.ctx)
      || canonicalJsonSha256(pointer) !== canonicalJsonSha256(prior.job.guidedHandoffV2)
      || strictGuidedTimestamp(row.createdAt) > current.job.updatedAt || String(row.createdAt) < prior.job.updatedAt
      || strictGuidedTimestamp(row.generationStartedAt) > String(row.createdAt)) throw new Error("Opening actual process activation lost its exact journal lineage");
  return { fact: row, hash, prior };
}
