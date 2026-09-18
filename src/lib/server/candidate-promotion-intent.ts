import path from "node:path";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { PromotionNodeState } from "./candidate-promotion-fs";

export type PromotionEntryKind = "move" | "copy" | "mutable";
export type PromotionMissingSourcePolicy =
  "reject" | "delete-destination";
export type PromotionIntentPhase =
  | "prepared"
  | "backed-up"
  | "commit-ready"
  | "committed"
  | "rolled-back"
  | "reconciliation-required";

export interface PromotionIntentEntry {
  kind: PromotionEntryKind;
  source: string | null;
  missingSource: PromotionMissingSourcePolicy | null;
  destination: string;
  backup: string | null;
  temporary: string;
  sourceState: PromotionNodeState | null;
  oldState: PromotionNodeState;
  committedState: PromotionNodeState | null;
}

export interface CandidatePromotionIntentV1 {
  schemaVersion: 1;
  kind: "candidate-promotion-transaction";
  transactionId: string;
  topologyHash: string;
  phase: PromotionIntentPhase;
  recoveryDirectory: string;
  entries: PromotionIntentEntry[];
  failures: string[];
}

export interface PromotionTopology {
  scopeRoot: string;
  recoveryRoot: string;
  reconciliationPath: string;
  transactionId: string;
  moves: PromotionTransfer[];
  copies: PromotionTransfer[];
  mutablePaths: string[];
}

export interface PromotionTransfer {
  source: string;
  destination: string;
  missingSource?: PromotionMissingSourcePolicy;
}

const HASH = /^[0-9a-f]{64}$/u;
const PHASES: PromotionIntentPhase[] = [
  "prepared",
  "backed-up",
  "commit-ready",
  "committed",
  "rolled-back",
  "reconciliation-required",
];

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  label: string,
): void {
  const observed = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (JSON.stringify(observed) !== JSON.stringify(expected)) {
    throw new Error(`${label} has unsupported or missing fields`);
  }
}

function absolute(value: unknown, label: string): string {
  if (typeof value !== "string" || !path.isAbsolute(value)) {
    throw new Error(`${label} must be an absolute path`);
  }
  return path.resolve(value);
}

function nodeState(value: unknown, label: string): PromotionNodeState {
  const row = record(value, label);
  if (row.kind === "missing") {
    exactKeys(row, ["kind"], label);
    return { kind: "missing" };
  }
  if (row.kind === "directory") {
    exactKeys(row, ["kind", "sha256"], label);
    if (typeof row.sha256 !== "string" || !HASH.test(row.sha256)) {
      throw new Error(`${label} digest is malformed`);
    }
    return { kind: "directory", sha256: row.sha256 };
  }
  exactKeys(row, ["kind", "sha256", "size"], label);
  if (row.kind !== "file" || typeof row.sha256 !== "string"
      || !HASH.test(row.sha256) || !Number.isSafeInteger(row.size)
      || Number(row.size) < 0) {
    throw new Error(`${label} file state is malformed`);
  }
  return { kind: "file", sha256: row.sha256, size: Number(row.size) };
}

function nullableState(value: unknown, label: string): PromotionNodeState | null {
  return value === null ? null : nodeState(value, label);
}

function entry(value: unknown, index: number): PromotionIntentEntry {
  const label = `promotion intent entry ${index}`;
  const row = record(value, label);
  exactKeys(row, [
    "kind", "source", "missingSource", "destination", "backup", "temporary",
    "sourceState", "oldState", "committedState",
  ], label);
  if (!["move", "copy", "mutable"].includes(String(row.kind))) {
    throw new Error(`${label} kind is malformed`);
  }
  const source = row.source === null ? null : absolute(row.source, `${label} source`);
  const missingSource = row.missingSource === null
    ? null : String(row.missingSource);
  const backup = row.backup === null ? null : absolute(row.backup, `${label} backup`);
  if (source === null ? missingSource !== null
    : !["reject", "delete-destination"].includes(missingSource ?? "")) {
    throw new Error(`${label} missing-source policy is malformed`);
  }
  return {
    kind: row.kind as PromotionEntryKind,
    source,
    missingSource: missingSource as PromotionMissingSourcePolicy | null,
    destination: absolute(row.destination, `${label} destination`),
    backup,
    temporary: absolute(row.temporary, `${label} temporary`),
    sourceState: nullableState(row.sourceState, `${label} sourceState`),
    oldState: nodeState(row.oldState, `${label} oldState`),
    committedState: nullableState(row.committedState, `${label} committedState`),
  };
}

export function parseCandidatePromotionIntentV1(
  value: unknown,
): CandidatePromotionIntentV1 {
  const row = record(value, "candidate promotion intent");
  exactKeys(row, [
    "schemaVersion", "kind", "transactionId", "topologyHash", "phase",
    "recoveryDirectory", "entries", "failures",
  ], "candidate promotion intent");
  if (row.schemaVersion !== 1
      || row.kind !== "candidate-promotion-transaction"
      || typeof row.transactionId !== "string" || !HASH.test(row.transactionId)
      || typeof row.topologyHash !== "string" || !HASH.test(row.topologyHash)
      || !PHASES.includes(row.phase as PromotionIntentPhase)
      || !Array.isArray(row.entries)
      || !Array.isArray(row.failures)
      || row.failures.some((item) => typeof item !== "string")) {
    throw new Error("candidate promotion intent is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "candidate-promotion-transaction",
    transactionId: row.transactionId,
    topologyHash: row.topologyHash,
    phase: row.phase as PromotionIntentPhase,
    recoveryDirectory: absolute(
      row.recoveryDirectory, "promotion recovery directory"),
    entries: row.entries.map(entry),
    failures: row.failures as string[],
  };
}

function topologyRows(topology: PromotionTopology): unknown[] {
  return [
    ...topology.moves.map((row) => ({
      kind: "move", ...row, missingSource: row.missingSource ?? "reject",
    })),
    ...topology.copies.map((row) => ({
      kind: "copy", ...row, missingSource: row.missingSource ?? "reject",
    })),
    ...topology.mutablePaths.map((destination) => ({
      kind: "mutable", source: null, missingSource: null, destination,
    })),
  ];
}

export function promotionTopologyHash(topology: PromotionTopology): string {
  return canonicalJsonSha256({
    scopeRoot: topology.scopeRoot,
    recoveryRoot: topology.recoveryRoot,
    reconciliationPath: topology.reconciliationPath,
    entries: topologyRows(topology),
  });
}
