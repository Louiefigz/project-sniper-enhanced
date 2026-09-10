import { existsSync } from "node:fs";
import path from "node:path";
import {
  parseProjectRevision,
  type ProjectRevision,
} from "@/lib/producer/contracts/project-revision";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readActiveHeadSync,
  readApprovedHeadSync,
  readAuthorityJsonSync,
  writeActiveHeadSync,
  writeApprovedHeadSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import {
  assertRevisionPlanObjectSync,
  revisionV2WriteFrom,
  writeProjectRevisionV2Sync,
} from "./producer-plan-authority";
import {
  parseProducerAdvanceRecordV1,
  parseProducerGenesisRecordV1,
  type ProducerAdvanceRecordV1,
} from "./producer-revision-store-model";

const GENESIS_NAME = "GENESIS.json";
const MAX_LINEAGE = 100_000;

export interface ProducerAuthorityGenesisOptions {
  approvedGenesis?: "qc-approved-import";
}

function genesisPath(paths: ProducerAuthorityPaths): string {
  return path.join(paths.advances, GENESIS_NAME);
}

export function advancePath(
  paths: ProducerAuthorityPaths,
  parentHash: string,
): string {
  return path.join(paths.advances, `${parentHash}.json`);
}

function revisionAt(
  paths: ProducerAuthorityPaths,
  hash: string,
): ProjectRevision {
  const revision = parseProjectRevision(
    assertObjectHashSync(paths.objects.revisions, hash));
  assertRevisionPlanObjectSync(paths, revision);
  return revision;
}

function refreshHeadCache(paths: ProducerAuthorityPaths, resolved: string): void {
  let cached: string | null = null;
  try {
    cached = readActiveHeadSync(paths);
  } catch {}
  if (cached !== resolved) writeActiveHeadSync(paths, resolved);
}

/** Resolve the canonical head from immutable genesis + one-winner parent advances. */
export function resolveProducerAuthorityHeadSync(
  producerDir: string,
): string {
  const paths = producerAuthorityPaths(producerDir);
  const start = genesisPath(paths);
  if (!existsSync(start)) throw new Error("producer revision authority is uninitialized");
  const genesis = parseProducerGenesisRecordV1(readAuthorityJsonSync(start));
  if (revisionAt(paths, genesis.revisionHash).parentRevisionHash !== null) {
    throw new Error("genesis revision has a parent");
  }
  const seen = new Set<string>();
  let current = genesis.revisionHash;
  for (let depth = 0; depth < MAX_LINEAGE; depth += 1) {
    if (seen.has(current)) throw new Error("producer revision lineage contains a cycle");
    seen.add(current);
    const candidatePath = advancePath(paths, current);
    if (!existsSync(candidatePath)) {
      refreshHeadCache(paths, current);
      return current;
    }
    const advance = parseProducerAdvanceRecordV1(
      readAuthorityJsonSync(candidatePath),
    );
    if (advance.expectedParentRevisionHash !== current) {
      throw new Error("producer advance path does not bind its expected parent");
    }
    const child = revisionAt(paths, advance.childRevisionHash);
    if (child.parentRevisionHash !== current) {
      throw new Error("producer child revision does not bind its parent");
    }
    current = advance.childRevisionHash;
  }
  throw new Error("producer revision lineage exceeds its safety limit");
}

export function initializeProducerAuthoritySync(
  producerDir: string,
  revisionValue: unknown,
  planObject: unknown,
  options: ProducerAuthorityGenesisOptions = {},
): { revisionHash: string; reused: boolean } {
  const paths = producerAuthorityPaths(producerDir);
  const revision = parseProjectRevision(revisionValue);
  if (revision.parentRevisionHash !== null) {
    throw new Error("producer authority genesis revision must have no parent");
  }
  if (options.approvedGenesis && revision.workflowState !== "QC_APPROVED") {
    throw new Error("approved genesis import must be QC_APPROVED");
  }
  const stored = writeProjectRevisionV2Sync({
    paths,
    planObject,
    revision: revisionV2WriteFrom(revision),
  });
  const result = publishImmutableAuthorityJsonSync(genesisPath(paths), {
    schemaVersion: 1,
    revisionHash: stored.revisionHash,
  });
  const resolved = resolveProducerAuthorityHeadSync(producerDir);
  if (resolved !== stored.revisionHash) {
    throw new Error("producer authority already has a different genesis");
  }
  if (options.approvedGenesis) {
    const approved = readApprovedHeadSync(paths);
    if (approved !== null && approved !== resolved) {
      throw new Error("approved genesis import conflicts with APPROVED_HEAD");
    }
    if (approved === null) writeApprovedHeadSync(paths, resolved);
  }
  return { revisionHash: stored.revisionHash, reused: result.reused };
}

/** Resolve the separately retained approved head without changing working truth. */
export function resolveProducerApprovedHeadSync(
  producerDir: string,
): string | null {
  const paths = producerAuthorityPaths(producerDir);
  const approved = readApprovedHeadSync(paths);
  if (approved === null) return null;
  revisionAt(paths, approved);
  const active = resolveProducerAuthorityHeadSync(producerDir);
  if (!revisionIsAncestorSync(paths, approved, active)) {
    throw new Error("APPROVED_HEAD is outside the active revision lineage");
  }
  return approved;
}

/** Select the exact QC-approved working revision as the approved head. */
export function approveProducerAuthorityHeadSync(
  producerDir: string,
  expectedActiveHead: string,
  expectedApprovedHead: string | null,
): string {
  const paths = producerAuthorityPaths(producerDir);
  const active = resolveProducerAuthorityHeadSync(producerDir);
  if (active !== expectedActiveHead) {
    throw new Error("working head changed before approval");
  }
  if (revisionAt(paths, active).workflowState !== "QC_APPROVED") {
    throw new Error("only a QC_APPROVED revision can advance APPROVED_HEAD");
  }
  const approved = resolveProducerApprovedHeadSync(producerDir);
  if (approved === active) return active;
  if (approved !== expectedApprovedHead) {
    throw new Error("approved head changed before approval");
  }
  writeApprovedHeadSync(paths, active);
  return active;
}

/**
 * Stage a proved QC child before its immutable parent advance. The caller must
 * publish that advance as its final fallible step or restore this mutable head.
 */
export function stageProducerApprovedHeadSync(
  producerDir: string,
  expectedApprovedHead: string | null,
  childRevisionHash: string,
): void {
  const paths = producerAuthorityPaths(producerDir);
  if (revisionAt(paths, childRevisionHash).workflowState !== "QC_APPROVED") {
    throw new Error("staged approved child is not QC_APPROVED");
  }
  const observed = readApprovedHeadSync(paths);
  if (observed === childRevisionHash) return;
  if (observed !== expectedApprovedHead) {
    throw new Error("approved head changed before child staging");
  }
  writeApprovedHeadSync(paths, childRevisionHash);
}

export function publishProducerAdvanceSync(
  paths: ProducerAuthorityPaths,
  record: ProducerAdvanceRecordV1,
): { reused: boolean } {
  const parsed = parseProducerAdvanceRecordV1(record);
  return publishImmutableAuthorityJsonSync(
    advancePath(paths, parsed.expectedParentRevisionHash),
    parsed,
  );
}

export function revisionIsAncestorSync(
  paths: ProducerAuthorityPaths,
  ancestorHash: string,
  descendantHash: string,
): boolean {
  let current: string | null = descendantHash;
  const seen = new Set<string>();
  while (current && seen.size < MAX_LINEAGE) {
    if (current === ancestorHash) return true;
    if (seen.has(current)) throw new Error("producer revision ancestry contains a cycle");
    seen.add(current);
    current = revisionAt(paths, current).parentRevisionHash;
  }
  return false;
}
