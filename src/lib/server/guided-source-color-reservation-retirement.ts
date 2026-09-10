/** Exact pending-reservation retirement only. No native cleanup, claim clearing or lease release. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { workspaceRoot } from "@/app/api/_lib/workspace";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseSourceColorRetirementAck, type SourceColorRetirementAck } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { createOpeningRecord, assertOpeningRecord } from "./guided-opening-process-activation";
import { assertSourceColorCleanupPendingMetadata, remainingSourceColorCleanupPending,
  type readSourceColorCleanupPending } from "./guided-source-color-cleanup-pending-read";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { freezeSourceColorValue } from "./guided-source-color-staging-hold";
import type { ProjectMutationLease } from "./project-mutation-lease";
import type { HeldGradeObservationResource } from "./grade-observation-resource";

type Pending = ReturnType<typeof readSourceColorCleanupPending>;
export interface SourceColorReservationRetirementInput {
  pending: Pending; projectLease: ProjectMutationLease; resource: HeldGradeObservationResource;
}
/** Code-only namespace/fault controls, never a caller override for unlink, proof, clock or success. */
export const sourceColorRetirementDependencies = { workspace: workspaceRoot };
export interface SourceColorRetirementFaults { afterUnlink?: () => void; afterAck?: () => void }
type Dependencies = typeof sourceColorRetirementDependencies;
const retirementHolds = new WeakMap<object, { check: () => number; owner: RetirementLifetime }>();

function present(file: string): boolean {
  try { fs.lstatSync(file); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}
function absent(file: string): void {
  if (present(file)) throw new Error("Source color retirement requires absence; an existing entry is retained");
}
function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source color retirement original ${label} changed`);
}

/** Keep exact original paths/inodes and the original pending owner throughout the destructive interval. */
class RetirementLifetime {
  readonly pending;
  readonly activePath;
  readonly ackPath;
  private readonly original;
  private readonly parents = new Map<string, bigint[]>();
  private active: bigint[] | null;
  private ack: bigint[] | null;
  private readonly projectGuard;
  private readonly resourceGuard;
  private budget: { started: number; remaining: number } | undefined;
  constructor(readonly input: SourceColorReservationRetirementInput, dependencies: Dependencies) {
    this.original = { ...input, resourcePath: input.resource.resource, resourceLease: input.resource.lease,
      releaseProject: input.projectLease.release, releaseResource: input.resource.lease.release, resourceCheck: input.resource.assertResource };
    this.pending = input.pending; assertSourceColorCleanupPendingMetadata(this.pending);
    if (this.pending.scope !== "current-pending-source-color-cleanup-not-retirement-or-approval") {
      throw new Error("Source color retirement requires the exact current pending journal, not history");
    }
    this.activePath = this.pending.fact.reservation.path;
    this.ackPath = path.join(path.dirname(this.pending.fact.archive.path), "retirement-ack.json");
    this.captureParents(path.dirname(this.activePath)); this.captureParents(path.dirname(this.ackPath));
    this.active = present(this.activePath) ? fileIdentity(this.activePath) : null;
    this.ack = present(this.ackPath) ? fileIdentity(this.ackPath) : null;
    const resource = path.join(fs.realpathSync(dependencies.workspace()), ".sniper-color-resource");
    if (this.activePath !== path.join(resource, "active.json") || input.resource.resource !== resource) {
      throw new Error("Source color retirement does not name the existing original global resource");
    }
    this.projectGuard = cutPreviewLeaseGuard(this.pending.job.ctx.dir, input.projectLease);
    this.resourceGuard = cutPreviewLeaseGuard(resource, input.resource.lease); this.metadata();
  }
  private captureParents(directory: string): void {
    for (;;) {
      const identity = directoryIdentity(directory), previous = this.parents.get(directory);
      if (previous) same(identity, previous, "parent during capture");
      this.parents.set(directory, identity);
      const parent = path.dirname(directory); if (parent === directory) return;
      directory = parent;
    }
  }
  private unchanged(): void {
    const i = this.input, o = this.original;
    if (i.pending !== o.pending || i.projectLease !== o.projectLease || i.resource !== o.resource
        || i.resource.resource !== o.resourcePath || i.resource.lease !== o.resourceLease
        || i.projectLease.release !== o.releaseProject || i.resource.lease.release !== o.releaseResource
        || i.resource.assertResource !== o.resourceCheck) throw new Error("Source color retirement original caller identity changed");
  }
  private resourceMetadata(): void {
    this.unchanged();
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity, "parent");
    if (this.active) same(fileIdentity(this.activePath), this.active, "active reservation identity");
    else absent(this.activePath);
    if (this.ack) same(fileIdentity(this.ackPath), this.ack, "acknowledgement identity");
    else absent(this.ackPath);
  }
  metadata = (): void => { this.unchanged(); assertSourceColorCleanupPendingMetadata(this.pending); this.resourceMetadata(); };
  /** Narrow resource-only tail after a later journal CAS; separate retained history must prove that edge. */
  resourceOwnership = (): void => { this.unchanged(); this.projectGuard(); this.resourceGuard(); this.resourceMetadata(); };
  finite = (): void => {
    this.metadata();
    if (!this.budget) throw new Error("Source color retirement has no original protected remainder");
    const elapsed = performance.now() - this.budget.started;
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= this.budget.remaining) throw new Error("Source color retirement exhausted its original protected remainder; retain pending evidence");
  };
  check = (): number => {
    this.metadata(); const started = performance.now(), remaining = remainingSourceColorCleanupPending(this.pending);
    this.projectGuard(); this.resourceGuard(); this.metadata();
    const elapsed = performance.now() - started;
    if (!Number.isFinite(elapsed) || elapsed < 0) throw new Error("Source color retirement original monotonic clock moved backwards");
    this.budget = { started: performance.now(), remaining: remaining - elapsed }; this.finite();
    return this.budget.remaining - (performance.now() - this.budget.started);
  };
  hasAck(): boolean { return this.ack !== null; }
  retire(): SourceColorRetirementAck["disposition"] {
    this.check();
    if (!this.active) return "already-absent-after-committed-intent";
    const original = this.pending.fact.reservation;
    const observed = observeCutPreviewFile(this.activePath, 8 * 1024 * 1024, false, this.finite);
    if (observed.sha256 !== original.sha256 || observed.sizeBytes !== original.sizeBytes) throw new Error("Source color retirement active bytes differ from the committed original archive");
    this.finite(); fs.unlinkSync(this.activePath); this.active = null;
    const descriptor = fs.openSync(path.dirname(this.activePath), fs.constants.O_RDONLY);
    try { fs.fsyncSync(descriptor); } finally { fs.closeSync(descriptor); }
    this.finite(); return "unlinked-original";
  }
  bindAck(): void {
    if (this.ack) throw new Error("Source color retirement cannot replace an original acknowledgement");
    this.ack = fileIdentity(this.ackPath); this.finite();
  }
  requireRetired(): void { absent(this.activePath); this.finite(); }
}

function buildAck(owner: RetirementLifetime, disposition: SourceColorRetirementAck["disposition"]) {
  const { fact, factHash, pendingJournalHash } = owner.pending;
  return parseSourceColorRetirementAck({ schemaVersion: 1, kind: "guided-opening-source-color-retirement",
    scope: "exact-reservation-retirement-not-process-cleanup-or-approval", claimHash: fact.claimHash,
    executionId: fact.executionId, cleanupAttemptId: fact.cleanupAttemptId, preparedFactHash: factHash,
    pendingJournalHash, reservation: fact.reservation, archive: fact.archive, disposition,
    observedAt: new Date().toISOString(), mediaSelected: false, openingApproved: false, deliveryApproved: false });
}

function assertAck(owner: RetirementLifetime, value: SourceColorRetirementAck): void {
  const expected = buildAck(owner, value.disposition);
  same({ ...value, observedAt: expected.observedAt }, expected, "acknowledgement bindings");
  if (value.observedAt < owner.pending.fact.createdAt || value.observedAt > expected.observedAt) {
    throw new Error("Source color retirement acknowledgement clock differs from its original pending fact");
  }
  owner.requireRetired();
}

function readAck(owner: RetirementLifetime) {
  const observed = observeCutPreviewFile(owner.ackPath, 128 * 1024, true, owner.finite);
  const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes)) as Record<string, unknown>;
  parseSourceColorRetirementAck(value); owner.finite(); return { ...observed, value };
}

function acknowledgement(owner: RetirementLifetime, faults: SourceColorRetirementFaults) {
  owner.check();
  if (owner.hasAck()) {
    owner.requireRetired(); const actual = readAck(owner), value = parseSourceColorRetirementAck(actual.value);
    assertAck(owner, value); return { path: owner.ackPath, sha256: actual.sha256, value: actual.value };
  }
  const disposition = owner.retire(); faults.afterUnlink?.(); owner.check(); owner.requireRetired();
  const value = buildAck(owner, disposition); assertAck(owner, value);
  const record = createOpeningRecord(owner.ackPath, value as unknown as Record<string, unknown>);
  owner.bindAck(); faults.afterAck?.(); owner.check(); owner.requireRetired();
  return record;
}

/** One exact marker may be removed, after committed cleanup; never touches source/job/container data.
 * A failed interval preserves pending state and any archive/ack. Existing ack recovery never overwrites it.
 */
export function retirePreparedSourceColorReservation(input: SourceColorReservationRetirementInput,
  dependencies: Dependencies = sourceColorRetirementDependencies, testOnly?: SourceColorRetirementFaults) {
  const controls = { ...dependencies }, faults = { ...testOnly }, owner = new RetirementLifetime(input, controls);
  const record = acknowledgement(owner, faults), ack = freezeSourceColorValue(parseSourceColorRetirementAck(record.value));
  const actual = readAck(owner);
  same(actual.sha256, record.sha256, "published acknowledgement raw SHA");
  same(canonicalJsonSha256(actual.value), canonicalJsonSha256(ack), "published acknowledgement value");
  const check = () => {
    const started = performance.now(), remaining = owner.check();
    assertOpeningRecord(record); assertAck(owner, ack); owner.finite();
    const elapsed = performance.now() - started;
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Source color retirement final checks exhausted the original protected remainder");
    return remaining - elapsed;
  };
  check();
  const result = Object.freeze({ scope: "exact-pending-reservation-retirement-not-journal-clearance-or-approval" as const,
    ack, reference: Object.freeze({ path: record.path, sha256: actual.sha256, sizeBytes: actual.sizeBytes }),
    pendingJournalHash: owner.pending.pendingJournalHash, preparedFactHash: owner.pending.factHash,
    claimRetained: true as const, mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const,
    assertCurrent: check });
  retirementHolds.set(result, { check, owner }); return result;
}

/** Actual live retirement only. A stored acknowledgement requires an explicit pending-journal recovery read. */
export function assertSourceColorReservationRetired(value: ReturnType<typeof retirePreparedSourceColorReservation>): void {
  const check = retirementHolds.get(value);
  if (!check) throw new Error("Source color retirement requires the actual original verified retirement");
  check.check();
}

/** Only the actual current retirement supplies its pending parent for the final CAS. */
export function pendingSourceColorRetirement(value: ReturnType<typeof retirePreparedSourceColorReservation>): Pending {
  const held = retirementHolds.get(value);
  if (!held) throw new Error("Source color retirement requires the actual original verified retirement");
  held.check(); return held.owner.pending;
}

/** Same original pending clock, with retirement and acknowledgement checks charged to it. */
export function remainingSourceColorRetirement(value: ReturnType<typeof retirePreparedSourceColorReservation>): number {
  const held = retirementHolds.get(value);
  if (!held) throw new Error("Source color retirement requires the actual original verified retirement");
  return held.check();
}

/** Live leases and exact retired-resource metadata only; not a journal/history/clock or approval check. */
export function assertSourceColorRetirementResourceOwnership(value: ReturnType<typeof retirePreparedSourceColorReservation>): void {
  const held = retirementHolds.get(value);
  if (!held) throw new Error("Source color retirement requires the actual original verified retirement");
  held.owner.resourceOwnership();
}
