/** Five original stopped-reader dependencies, never current sources, grade jobs or executable files. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { readOpeningProcessActivation } from "./guided-opening-process-activation";
import type { HeldOpeningClaim, readStoppedOpeningProcess } from "./guided-opening-process";

export const CLEANUP_MEDIA_ROLES = ["activation", "priorJournal", "intent", "outcome", "ledger"] as const;
export type CleanupMediaRole = typeof CLEANUP_MEDIA_ROLES[number];
export interface CleanupMediaReference { role: CleanupMediaRole; path: string; sha256: string }
export type CaptureCleanupMediaReference = (reference: CleanupMediaReference) => Buffer;
const NAMES = { intent: "media-process-intent.json", outcome: "media-process-result.json", ledger: "owned-process-ledger.media.jsonl" };

/** Exact paths are closed before IO; the pre-activation journal is selected only by its authenticated hash. */
export function cleanupMediaReference(value: CleanupMediaReference, held: HeldOpeningClaim): number {
  const row = objectValue(value, "cleanup historical media reference");
  exactKeys(row, ["role", "path", "sha256"], ["role", "path", "sha256"], "cleanup historical media reference");
  if (!CLEANUP_MEDIA_ROLES.includes(value.role)) throw new Error("Cleanup historical media role is unsupported");
  sha256(value.sha256, "original media reference SHA"); openingAbsolutePath(value.path);
  const producer = openingAbsolutePath(held.job.ctx.dir), root = path.dirname(openingAbsolutePath(held.claimPath));
  let expected: string;
  if (value.role === "activation") {
    const original = sha256(held.job.guidedHandoffV2?.openingProcessOutcomeHash, "original media activation SHA");
    if (value.sha256 !== original) throw new Error("Cleanup original media activation reference changed");
    expected = path.join(producer, ".sniper-authority-v1/objects/receipts", `${original}.json`);
  } else if (value.role === "priorJournal") expected = path.join(producer, "human-cut-job-snapshots", `${value.sha256}.json`);
  else expected = path.join(root, NAMES[value.role]);
  if (value.path !== expected) throw new Error("Cleanup historical media reference namespace changed");
  return value.role === "ledger" ? 32 * 1024 * 1024 : 16 * 1024 * 1024;
}

function json(bytes: Buffer): Record<string, unknown> {
  return objectValue(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)), "original media metadata");
}

/** Capture/hash each original dependency before any caller callback, then use the existing lineage parser. */
export function captureSourceColorCleanupMedia(held: HeldOpeningClaim, capture: CaptureCleanupMediaReference): void {
  const producer = held.job.ctx.dir, root = path.dirname(held.claimPath);
  const hash = sha256(held.job.guidedHandoffV2?.openingProcessOutcomeHash, "original media activation SHA");
  const activation = json(capture({ role: "activation", path: path.join(producer, ".sniper-authority-v1/objects/receipts", `${hash}.json`), sha256: hash }));
  const prior = sha256(activation.beforeJournalHash, "original pre-activation journal SHA");
  capture({ role: "priorJournal", path: path.join(producer, "human-cut-job-snapshots", `${prior}.json`), sha256: prior });
  capture({ role: "intent", path: path.join(root, NAMES.intent), sha256: sha256(activation.intentSha256, "original media intent SHA") });
  const outcome = json(capture({ role: "outcome", path: path.join(root, NAMES.outcome),
    sha256: sha256(activation.outcomeSha256, "original media outcome SHA") }));
  capture({ role: "ledger", path: path.join(root, NAMES.ledger), sha256: sha256(outcome.ledgerSha256, "original media ledger SHA") });
  const actual = readOpeningProcessActivation(producer, held);
  if (actual.hash !== hash || !isDeepStrictEqual(actual.fact, activation) || actual.prior.sha256 !== prior) {
    throw new Error("Cleanup original media activation lineage changed");
  }
}

/** Repeated actual stopped returns must name the same first-held raw media proof, not merely equal metadata. */
export function assertCleanupMediaReturn(refs: ReadonlyMap<CleanupMediaRole, CleanupMediaReference>,
  stopped: ReturnType<typeof readStoppedOpeningProcess>): void {
  if (stopped.receiptSha256 !== refs.get("outcome")?.sha256 || stopped.intentHash !== refs.get("intent")?.sha256
      || stopped.receipt.intentHash !== refs.get("intent")?.sha256 || stopped.receipt.ledgerSha256 !== refs.get("ledger")?.sha256) {
    throw new Error("Cleanup stopped return differs from its original media raw references");
  }
}
