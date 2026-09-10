/** Finite original cleanup proof for a live controller; never native cleanup or cold adoption authority. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readCommittedOpeningCleanup } from "./guided-opening-cleanup-store";
import { captureSourceColorCleanupMedia } from "./guided-source-color-cleanup-attempt-media";
import { directoryIdentity, fileIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";

type Cleanup = ReturnType<typeof readCommittedOpeningCleanup>;
function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Opening controller original cleanup proof changed");
}

/** Current journal/selection can advance; the original claim, stop, cleanup and retirement cannot. */
function projection(value: Cleanup) {
  return { cleanupHash: value.cleanupHash, held: value.held, receipt: value.receipt, evidence: value.evidence,
    color: "pending" in value ? { prepared: value.pending.fact, pendingJournalHash: value.pending.pendingJournalHash,
      retirementAck: value.retirementAck } : null };
}

/** Keep exact finite files before later callbacks; media ledger bytes are not JSON documents. */
export function holdOpeningControllerCleanup(value: Cleanup) {
  const fixed = snapshotSourceColorMetadata(projection(value)), files = new Map<string, bigint[]>();
  const parents = new Map<string, bigint[]>(), held = value.held, dir = held.job.ctx.dir;
  const fact = "pending" in value ? value.pending.fact : value.receipt;
  const root = path.join(path.dirname(held.claimPath), "cleanup-attempts", String(fact.cleanupAttemptId));
  const metadata = () => {
    same(projection(value), fixed);
    for (const [file, identity] of files) same(fileIdentity(file), identity);
    for (const [directory, identity] of parents) same(directoryIdentity(directory), identity);
    assertOpeningFailureAbsent(path.join(root, "failure.json"));
  };
  const capture = (file: string, sha256: string) => {
    const identity = fileIdentity(file); files.set(file, identity);
    for (let directory = path.dirname(file); !parents.has(directory); directory = path.dirname(directory)) {
      parents.set(directory, directoryIdentity(directory));
    }
    const observed = observeCutPreviewFile(file, 32 * 1024 * 1024, true, metadata);
    if (observed.sha256 !== sha256) throw new Error("Opening controller cleanup raw reference differs");
    metadata(); return observed.bytes;
  };
  capture(held.claimPath, held.claimSha256); capture(held.claim.inputPath, held.claim.inputSha256);
  captureSourceColorCleanupMedia(held, ref => capture(ref.path, ref.sha256));
  const object = (hash: unknown) => capture(path.join(dir, ".sniper-authority-v1/objects/receipts", `${hash}.json`), String(hash));
  object(value.cleanupHash); object(held.claimHash); object(fact.cleanupResultHash);
  capture(path.join(root, "start.json"), String(fact.cleanupStartSha256));
  capture(path.join(root, "output.json"), String(fact.cleanupOutputSha256));
  capture(path.join(dir, "human-cut-job-snapshots", `${fact.beforeJournalHash}.json`), String(fact.beforeJournalHash));
  if ("pending" in value) {
    const ledger = value.evidence.output.ledger as { path: string; sha256: string };
    same(ledger.path, path.join(root, "owned-process-ledger.cleanup.jsonl")); capture(ledger.path, ledger.sha256);
    object(value.receipt.preparedFactHash);
    capture(path.join(root, "invocation.json"), value.pending.fact.cleanupInvocationSha256);
    capture(value.pending.fact.archive.path, value.pending.fact.archive.sha256);
    capture(value.receipt.retirementAck.path, value.receipt.retirementAck.sha256);
    capture(path.join(dir, "human-cut-job-snapshots", `${value.receipt.pendingJournalHash}.json`), value.receipt.pendingJournalHash);
  }
  metadata();
  return Object.freeze({
    /** Reuse the actual bounded current proof reader, not the expired old current-journal callback. */
    check(): void {
      metadata(); const current = readCommittedOpeningCleanup(dir); same(projection(current), fixed); metadata();
      if (current.job.guidedHandoffV2?.openingExecutionClaimHash || current.receipt.claimRetained !== false) {
        throw new Error("Opening controller cleanup no longer clears exact ownership");
      }
    },
    metadata,
  });
}
