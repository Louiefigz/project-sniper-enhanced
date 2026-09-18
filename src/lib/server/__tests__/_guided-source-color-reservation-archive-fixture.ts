/** Literal TEST archive metadata; original claim/process admission is a declared stub boundary. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { TestContext } from "node:test";
import { holdSourceColorCleanupReservation } from "../guided-source-color-cleanup-hold";
import { readSourceColorReservationArchive, writeSourceColorReservationArchive,
  type ReadSourceColorReservationArchive, type WriteSourceColorReservationArchive } from "../guided-source-color-reservation-archive";
import { sourceColorRecoveryFixture } from "./_guided-source-color-resource-recovery-fixture";

const ATTEMPT = "00000000-0000-4000-8000-000000000031";

/** Exact TEMP files/lease, actual raw metadata hold, no real process reader or native worker. */
export function sourceColorArchiveFixture(t: TestContext) {
  const original = sourceColorRecoveryFixture(t), { held, stopped } = original.input;
  assert(stopped.sourceColor);
  const attempt = path.join(path.dirname(held.claimPath), "cleanup-attempts", ATTEMPT);
  assert(attempt.startsWith(original.staging.root + path.sep));
  fs.mkdirSync(attempt, { recursive: true, mode: 0o700 });
  const callbacks = { guard: () => {}, remaining: () => 300_000 }, events = { guards: 0, remaining: 0 };
  const guard = () => { events.guards++; callbacks.guard(); };
  const remainingMs = () => { events.remaining++; return callbacks.remaining(); };
  const reservation = holdSourceColorCleanupReservation({ held, reference: stopped.sourceColor,
    resourceDir: original.staging.resource.resource, guard: original.staging.resource.assertResource, remainingMs });
  const context: WriteSourceColorReservationArchive = { held, reservation, attemptId: ATTEMPT, guard, remainingMs };
  const archivePath = path.join(attempt, "reservation.json"), bytes = fs.readFileSync(original.staged.reservation.path);
  const readerContext = (archive: ReturnType<typeof writeSourceColorReservationArchive>["archive"]): ReadSourceColorReservationArchive => ({
    held, reference: structuredClone(stopped.sourceColor!), archive: structuredClone(archive), attemptId: ATTEMPT, guard, remainingMs,
  });
  return { ...original, context, callbacks, events, attempt, archivePath, bytes,
    write: () => writeSourceColorReservationArchive(context), readerContext,
    read: (archive: ReturnType<typeof writeSourceColorReservationArchive>["archive"]) => readSourceColorReservationArchive(readerContext(archive)) };
}

/** Faults may access only this fixture's exact two original regular files. */
function faultTarget(f: ReturnType<typeof sourceColorArchiveFixture>, file: string): void {
  assert([f.archivePath, f.staged.reservation.path].includes(file));
  assert(file.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
}

/** Keep replacement bytes and unlinking confined to the declared temporary metadata target. */
export function replaceArchiveFixtureFile(f: ReturnType<typeof sourceColorArchiveFixture>, file: string, bytes?: Buffer): void {
  faultTarget(f, file);
  const temporary = path.join(path.dirname(file), "TEST-replacement-metadata.json");
  fs.writeFileSync(temporary, bytes ?? fs.readFileSync(file), { flag: "wx", mode: 0o600 });
  fs.renameSync(temporary, file);
}

/** Removing TEST active metadata models retirement but grants no real retirement authority. */
export function removeArchiveFixtureActive(f: ReturnType<typeof sourceColorArchiveFixture>): void {
  faultTarget(f, f.staged.reservation.path); fs.unlinkSync(f.staged.reservation.path);
}
