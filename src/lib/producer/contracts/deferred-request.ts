import {
  parseEditRequestV1,
  type EditRequestV1,
} from "./edit-request";
import {
  parseTimingAnchorV1,
  type TimingAnchorV1,
} from "./timing-anchor";
import {
  exactKeys,
  objectValue,
  sha256,
  stableId,
  uniqueStrings,
} from "./validation";

export interface AnchorMigrationV1 {
  oldTimelineMapHash: string;
  newTimelineMapHash: string;
  successors: Record<string, string[]>;
  segmentVersions: Record<string, number>;
  tombstones: string[];
}

export type AnchorResolutionV1 =
  | { status: "resolved"; anchor: TimingAnchorV1; explanation: string }
  | { status: "ambiguous" | "dangling"; explanation: string };

export interface DeferredClauseBindingV1 {
  clauseId: string;
  anchor: TimingAnchorV1;
}

export interface DeferredResolutionReceiptV1 {
  schemaVersion: 1;
  requestId: string;
  oldTimelineMapHash: string;
  newTimelineMapHash: string;
  rows: Array<{
    clauseId: string;
    status: AnchorResolutionV1["status"];
    anchor?: TimingAnchorV1;
    explanation: string;
  }>;
}

function version(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1) {
    throw new Error(`${label} must be a positive safe integer`);
  }
  return Number(value);
}

function migrationRecord(
  value: unknown,
  label: string,
  item: (entry: unknown, entryLabel: string) => unknown,
): Record<string, unknown> {
  const row = objectValue(value, label);
  return Object.fromEntries(Object.entries(row).map(([key, entry]) => [
    stableId(key, `${label} key`),
    item(entry, `${label}.${key}`),
  ]));
}

export function parseAnchorMigrationV1(value: unknown): AnchorMigrationV1 {
  const row = objectValue(value, "AnchorMigrationV1");
  const keys = [
    "oldTimelineMapHash", "newTimelineMapHash", "successors",
    "segmentVersions", "tombstones",
  ];
  exactKeys(row, keys, keys, "AnchorMigrationV1");
  return {
    oldTimelineMapHash: sha256(row.oldTimelineMapHash, "oldTimelineMapHash"),
    newTimelineMapHash: sha256(row.newTimelineMapHash, "newTimelineMapHash"),
    successors: migrationRecord(
      row.successors,
      "successors",
      (entry, label) => uniqueStrings(entry, label, stableId),
    ) as Record<string, string[]>,
    segmentVersions: migrationRecord(
      row.segmentVersions,
      "segmentVersions",
      version,
    ) as Record<string, number>,
    tombstones: uniqueStrings(row.tombstones, "tombstones", stableId),
  };
}

function stableSuccessor(
  id: string,
  migration: AnchorMigrationV1,
): { status: "resolved"; id: string } | AnchorResolutionV1 {
  if (migration.tombstones.includes(id)) {
    return { status: "dangling", explanation: `${id} was removed` };
  }
  const successors = migration.successors[id];
  if (!successors) return { status: "resolved", id };
  if (successors.length !== 1) {
    return {
      status: successors.length ? "ambiguous" : "dangling",
      explanation: `${id} has ${successors.length} valid successors`,
    };
  }
  return { status: "resolved", id: successors[0] };
}

function resolved(
  anchor: TimingAnchorV1,
  explanation: string,
): AnchorResolutionV1 {
  return { status: "resolved", anchor: parseTimingAnchorV1(anchor), explanation };
}

function namedAnchor(
  anchor: Extract<TimingAnchorV1,
    { type: "semantic-beat" | "section" | "music-beat" }>,
  migration: AnchorMigrationV1,
): AnchorResolutionV1 {
  const identity = anchor.type === "semantic-beat"
    ? { key: "beatId" as const, value: anchor.beatId }
    : anchor.type === "section"
      ? { key: "sectionId" as const, value: anchor.sectionId }
      : { key: "cueId" as const, value: anchor.cueId };
  const mapped = stableSuccessor(identity.value, migration);
  if (mapped.status !== "resolved" || !("id" in mapped)) return mapped;
  return resolved({
    ...anchor,
    [identity.key]: mapped.id,
  } as TimingAnchorV1, `${identity.key} resolved uniquely`);
}

function transcriptAnchor(
  anchor: Extract<TimingAnchorV1, { type: "transcript-range" }>,
  migration: AnchorMigrationV1,
): AnchorResolutionV1 {
  const start = stableSuccessor(anchor.startWordId, migration);
  const end = stableSuccessor(anchor.endWordId, migration);
  if (start.status !== "resolved" || !("id" in start)) return start;
  if (end.status !== "resolved" || !("id" in end)) return end;
  return resolved({
    ...anchor,
    startWordId: start.id,
    endWordId: end.id,
  }, "transcript word range resolved uniquely");
}

function segmentAnchor(
  anchor: Extract<TimingAnchorV1, { type: "cut-segment" }>,
  migration: AnchorMigrationV1,
): AnchorResolutionV1 {
  if (anchor.timelineMapHash !== migration.oldTimelineMapHash) {
    return { status: "dangling", explanation: "anchor does not bind the old timeline" };
  }
  const mapped = stableSuccessor(anchor.segmentId, migration);
  if (mapped.status !== "resolved" || !("id" in mapped)) return mapped;
  const nextVersion = migration.segmentVersions[mapped.id];
  if (!nextVersion) {
    return {
      status: "ambiguous",
      explanation: `segment ${mapped.id} has no proved child version`,
    };
  }
  return resolved({
    ...anchor,
    segmentId: mapped.id,
    elementVersion: nextVersion,
    timelineMapHash: migration.newTimelineMapHash,
  }, "cut-segment anchor resolved against exact child timeline");
}

function sourceAnchor(
  anchor: Extract<TimingAnchorV1, { type: "source-time" }>,
  migration: AnchorMigrationV1,
): AnchorResolutionV1 {
  const mapped = stableSuccessor(anchor.sourceId, migration);
  if (mapped.status !== "resolved" || !("id" in mapped)) return mapped;
  return resolved({
    ...anchor,
    sourceId: mapped.id,
  }, mapped.id === anchor.sourceId
    ? "source identity remained stable"
    : "source identity resolved to its unique proved successor");
}

/** Re-resolve one anchor; ambiguous or removed identity never snaps nearby. */
export function resolveTimingAnchorV1(
  value: TimingAnchorV1,
  migrationValue: AnchorMigrationV1,
): AnchorResolutionV1 {
  const anchor = parseTimingAnchorV1(value);
  const migration = parseAnchorMigrationV1(migrationValue);
  if (anchor.type === "timeline-frame") {
    if (anchor.timelineMapHash !== migration.oldTimelineMapHash) {
      return { status: "dangling", explanation: "frame anchor binds another timeline" };
    }
    return resolved({
      ...anchor,
      timelineMapHash: migration.newTimelineMapHash,
    }, "intentional output frame remained fixed");
  }
  if (anchor.type === "source-time") return sourceAnchor(anchor, migration);
  if (anchor.type === "transcript-range") {
    return transcriptAnchor(anchor, migration);
  }
  if (anchor.type === "cut-segment") return segmentAnchor(anchor, migration);
  return namedAnchor(anchor, migration);
}

function bindingMap(
  bindings: DeferredClauseBindingV1[],
): Map<string, TimingAnchorV1> {
  const result = new Map<string, TimingAnchorV1>();
  for (const binding of bindings) {
    const clauseId = stableId(binding.clauseId, "deferred binding clauseId");
    if (result.has(clauseId)) throw new Error(`duplicate deferred binding ${clauseId}`);
    result.set(clauseId, parseTimingAnchorV1(binding.anchor));
  }
  return result;
}

/** Transition every deferred treatment clause after its cut blockers commit. */
export function reresolveDeferredRequestV1(
  requestValue: EditRequestV1,
  bindings: DeferredClauseBindingV1[],
  migration: AnchorMigrationV1,
): { request: EditRequestV1; receipt: DeferredResolutionReceiptV1 } {
  const request = parseEditRequestV1(requestValue);
  const anchors = bindingMap(bindings);
  const clauses = new Map(request.clauses.map((clause) => [clause.clauseId, clause]));
  const deferred = request.clauses.filter((clause) => clause.state === "deferred");
  if (deferred.length !== anchors.size) {
    throw new Error("every deferred clause requires exactly one anchor binding");
  }
  const rows = deferred.map((clause) => {
    if (clause.blockingClauseIds.some((id) => clauses.get(id)?.state !== "committed")) {
      throw new Error(`deferred clause ${clause.clauseId} still has uncommitted blockers`);
    }
    const outcome = resolveTimingAnchorV1(anchors.get(clause.clauseId)!, migration);
    return { clause, outcome };
  });
  const byId = new Map(rows.map((row) => [row.clause.clauseId, row.outcome]));
  const updated = parseEditRequestV1({
    ...request,
    clauses: request.clauses.map((clause) => {
      const outcome = byId.get(clause.clauseId);
      if (!outcome) return clause;
      return {
        ...clause,
        // A removed anchor is a blocking clarification, not a new clause enum.
        // Preserve the more precise dangling diagnosis in the resolution receipt.
        state: outcome.status === "resolved" ? "compiled" : "ambiguous",
        disposition: outcome.explanation,
      };
    }),
  });
  return {
    request: updated,
    receipt: {
      schemaVersion: 1,
      requestId: request.requestId,
      oldTimelineMapHash: migration.oldTimelineMapHash,
      newTimelineMapHash: migration.newTimelineMapHash,
      rows: rows.map(({ clause, outcome }) => ({
        clauseId: clause.clauseId,
        status: outcome.status,
        ...("anchor" in outcome ? { anchor: outcome.anchor } : {}),
        explanation: outcome.explanation,
      })),
    },
  };
}
