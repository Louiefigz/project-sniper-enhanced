/** All prior completed attempts, never permission to launch, adopt, commit, retire or release. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { parsePreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { CleanupHistoryHold, type SourceColorCleanupHistoryInput } from "./guided-source-color-cleanup-history-hold";
import { readSourceColorCleanupAttempt, sourceColorCleanupAttemptReadDependencies,
  assertSourceColorCleanupAttemptMetadata } from "./guided-source-color-cleanup-attempt-read";
import { readOwnedProcessLedger, unreapedRows, unrecordedSpawns } from "./guided-opening-process-ledger";
import { assertCleanupMediaReturn } from "./guided-source-color-cleanup-attempt-media";
import { freezeSourceColorValue } from "./guided-source-color-staging-hold";

export type { SourceColorCleanupHistoryInput } from "./guided-source-color-cleanup-history-hold";
type Dependencies = typeof sourceColorCleanupAttemptReadDependencies;
const metadataHolds = new WeakMap<object, () => void>();

/** Normal-return history cannot upgrade unmatched native intent or an unreaped PID into absence. */
function balanced(directory: string): void {
  const rows = readOwnedProcessLedger(directory, "cleanup");
  if (unreapedRows(rows).length || unrecordedSpawns(rows).length) throw new Error("Cleanup history has unbalanced intent/spawn/reap ownership");
}
function readAttempt(hold: CleanupHistoryHold, attemptId: string, controls: Dependencies) {
  const directory = path.join(hold.directory, attemptId), original = hold.observe(path.join(directory, "prepared.json"));
  const fact = freezeSourceColorValue(parsePreparedSourceColorCleanupFact(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(original.bytes))));
  if (fact.cleanupAttemptId !== attemptId) throw new Error("Cleanup history prepared fact names another attempt");
  balanced(directory); hold.check();
  const evidence = readSourceColorCleanupAttempt({ held: hold.input.held, fact, guard: hold.check, remainingMs: hold.remaining }, controls);
  assertCleanupMediaReturn(hold.media, evidence.stop); hold.check();
  return Object.freeze({ attemptId, preparedRef: original.ref, fact, factHash: canonicalJsonSha256(fact), evidence });
}
type Attempt = ReturnType<typeof readAttempt>;

function validateSameHistory(attempts: readonly Attempt[]): void {
  const first = attempts[0].evidence;
  for (const row of attempts) {
    if (!isDeepStrictEqual(row.evidence.stop, first.stop) || !isDeepStrictEqual(row.evidence.containerNames, first.containerNames)) {
      throw new Error("Cleanup history attempts differ from the same original media/reservation/full names");
    }
  }
}

/** All six exact files per attempt and five original media dependencies are held before caller callbacks.
 * The 32-attempt/64MiB cap counts unique original metadata, including actual raw lengths.
 * Repeated validation IO still spends the SAME original allowance. Installed tools, sources,
 * active.json and current journal are not read; the later adoption owner must authenticate
 * its current precleanup journal and actual leases. Missing/retired/partial attempts refuse.
 */
export function readSourceColorCleanupHistory(input: SourceColorCleanupHistoryInput,
  dependencies: Dependencies = sourceColorCleanupAttemptReadDependencies) {
  const controls = Object.freeze({ ...dependencies }), hold = new CleanupHistoryHold(input, controls.media);
  return hold.run(() => {
    hold.observeAll();
    const attempts = Object.freeze(hold.attemptIds.map(id => readAttempt(hold, id, controls)));
    validateSameHistory(attempts);
    const metadata = () => {
      hold.assertMetadata();
      for (const row of attempts) assertSourceColorCleanupAttemptMetadata(row.evidence);
      hold.assertMetadata();
    };
    const assertCurrent = () => hold.run(() => {
      for (const row of attempts) {
        hold.observe(row.preparedRef.path); balanced(path.dirname(row.preparedRef.path));
        row.evidence.assertCurrent(); hold.check();
      }
      validateSameHistory(attempts); metadata();
    });
    const result = Object.freeze({ scope: "all-prior-completed-source-color-cleanup-not-adoption-or-retirement" as const,
      attempts, assertCurrent });
    metadata(); hold.check(); metadataHolds.set(result, metadata); return result;
  });
}
export type SourceColorCleanupHistoryEvidence = ReturnType<typeof readSourceColorCleanupHistory>;

/** Private successful-read identity only; does not run owner callbacks or assert clock/lease authority. */
export function assertSourceColorCleanupHistoryMetadata(value: SourceColorCleanupHistoryEvidence): void {
  const metadata = metadataHolds.get(value);
  if (!metadata) throw new Error("Cleanup history metadata requires the actual original read evidence");
  metadata();
}
