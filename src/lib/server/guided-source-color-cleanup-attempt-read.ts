/** Historical raw attempt evidence, never commit, reservation retirement or media selection authority.
 * Callers authenticate the original held claim/prepared fact and persistent historical guard.
 * No current active reservation, selected source, job or installed tool is read.
 */
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { ownershipUnresolved, readStoppedOpeningProcess } from "./guided-opening-process";
import { liveRecordedDescendants, observeOwnedWorkerLedger } from "./guided-opening-process-ledger";
import { readSourceColorReservationArchive } from "./guided-source-color-reservation-archive";
import { CleanupAttemptReadHold, type SourceColorCleanupAttemptReadInput } from "./guided-source-color-cleanup-attempt-hold";
import { validateCleanupAttemptRecords, type CleanupAttemptRecords } from "./guided-source-color-cleanup-attempt-contract";
import { freezeSourceColorValue } from "./guided-source-color-staging-hold";
import { assertCleanupMediaReturn, captureSourceColorCleanupMedia } from "./guided-source-color-cleanup-attempt-media";

export type { SourceColorCleanupAttemptReadInput } from "./guided-source-color-cleanup-attempt-hold";
/** Native/process authority is not replaceable by JSON; these are explicit code-only TEST leaves. */
export const sourceColorCleanupAttemptReadDependencies = {
  stopped: readStoppedOpeningProcess, ledger: observeOwnedWorkerLedger, descendants: liveRecordedDescendants,
  media: captureSourceColorCleanupMedia,
};
type Dependencies = typeof sourceColorCleanupAttemptReadDependencies;
type Stopped = ReturnType<typeof readStoppedOpeningProcess>;
type Archive = ReturnType<typeof readSourceColorReservationArchive>;
const metadataHolds = new WeakMap<object, () => void>();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Cleanup attempt original ${label} changed`);
}
function settled(current: Stopped, hold: CleanupAttemptReadHold): void {
  if (current.receipt.schemaVersion !== 3 || current.receipt.groupStopped !== true || !current.sourceColor
      || ownershipUnresolved(current) || current.liveDescendants.length || current.unknownDescendants.length
      || current.unrecordedSpawns.length || current.receiptSha256 !== hold.fact.processOutcomeSha256) {
    throw new Error("Cleanup history requires actual resolved original V3 media settlement");
  }
}

/** Bind the actual first return immediately; later callbacks cannot replace its proof baseline. */
class AttemptRead {
  readonly hold;
  private stopped: Stopped | undefined;
  private records: CleanupAttemptRecords | undefined;
  private archive: Archive | undefined;
  constructor(input: SourceColorCleanupAttemptReadInput, readonly controls: Dependencies) {
    this.hold = new CleanupAttemptReadHold(input, controls.media);
  }
  private readStopped(): Stopped {
    const current = this.controls.stopped(this.hold.input.held);
    const captured = freezeSourceColorValue(structuredClone(current));
    this.hold.check(); settled(captured, this.hold); assertCleanupMediaReturn(this.hold.media, captured);
    if (this.stopped) same(captured, this.stopped, "media stopped evidence");
    else this.stopped = captured;
    return captured;
  }
  private cleanupLedger(script: string): void {
    const ledger = this.records!.output.ledger as { path: string; sha256: string };
    const actual = this.controls.ledger(this.hold.directory, "cleanup", script, ledger.sha256);
    same(actual, ledger.sha256, "cleanup ledger raw SHA"); this.hold.check();
    const descendants = this.controls.descendants(this.hold.directory, "cleanup");
    exactKeys(objectValue(descendants, "cleanup descendants"), ["live", "unknown", "unrecordedSpawns"],
      ["live", "unknown", "unrecordedSpawns"], "cleanup descendants");
    if (!Array.isArray(descendants.live) || !Array.isArray(descendants.unknown) || !Array.isArray(descendants.unrecordedSpawns)
        || descendants.live.length || descendants.unknown.length || descendants.unrecordedSpawns.length) {
      throw new Error("Cleanup history has unresolved original cleanup descendants");
    }
    this.hold.check();
  }
  private validate() {
    const stopped = this.readStopped(), archive = this.archive!;
    archive.assertCurrent();
    const parsed = validateCleanupAttemptRecords(this.hold.input, this.records!, stopped, archive.containerNames);
    this.cleanupLedger(parsed.tools.script); this.hold.check();
    return parsed;
  }
  read() {
    return this.hold.run(() => {
      const stopped = this.readStopped();
      this.records = freezeSourceColorValue({ start: this.hold.read("start"), invocation: this.hold.read("invocation"), output: this.hold.read("output") });
      this.archive = readSourceColorReservationArchive({ held: this.hold.input.held, reference: stopped.sourceColor!,
        attemptId: this.hold.fact.cleanupAttemptId, archive: this.hold.fact.archive, guard: this.hold.check, remainingMs: this.hold.remaining });
      const parsed = this.validate();
      const result = Object.freeze({ scope: "historical-exact-source-color-cleanup-attempt-not-retirement-or-approval" as const,
        fact: this.hold.fact, ...this.records, stop: stopped, result: freezeSourceColorValue(structuredClone(parsed.result)),
        tools: freezeSourceColorValue(structuredClone(parsed.tools)), archive: this.archive.archive, containerNames: this.archive.containerNames,
        retirementObserved: false as const, mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const,
        assertCurrent: () => this.hold.run(() => { this.validate(); }) });
      this.hold.check(); metadataHolds.set(result, this.hold.assertMetadata); return result;
    });
  }
}

/** Read only exact authenticated references; never discover or retire a current reservation. */
export function readSourceColorCleanupAttempt(input: SourceColorCleanupAttemptReadInput,
  dependencies: Dependencies = sourceColorCleanupAttemptReadDependencies) {
  return new AttemptRead(input, Object.freeze({ ...dependencies })).read();
}

/** Callback-free final metadata only, authenticated by actual successful read identity.
 * The enclosing owner separately proves its same clock/lease and charges this sweep.
 */
export function assertSourceColorCleanupAttemptMetadata(value: ReturnType<typeof readSourceColorCleanupAttempt>): void {
  const check = metadataHolds.get(value);
  if (!check) throw new Error("Cleanup attempt metadata requires its actual original read evidence");
  check();
}
