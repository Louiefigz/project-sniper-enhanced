import {
  parseProjectRevisionV2,
  type ProjectRevision,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import { objectValue } from "@/lib/producer/contracts/validation";
import { planObjectContentHash } from "./auto-edit-authority";
import {
  assertObjectHashSync,
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";

export type ProjectRevisionV2Write = Omit<
  ProjectRevisionV2,
  "schemaVersion" | "planObjectHash"
>;

interface RevisionWriteInput {
  paths: ProducerAuthorityPaths;
  revision: ProjectRevisionV2Write;
  planObject: unknown;
}

export interface StoredProjectRevisionV2 {
  revision: ProjectRevisionV2;
  revisionHash: string;
  planObjectHash: string;
}

export function revisionV2WriteFrom(
  revision: ProjectRevision,
): ProjectRevisionV2Write {
  const {
    schemaVersion: _schemaVersion,
    ...versioned
  } = revision;
  void _schemaVersion;
  if ("planObjectHash" in versioned) {
    const { planObjectHash: _planObjectHash, ...write } = versioned;
    void _planObjectHash;
    return write;
  }
  return versioned;
}

function exactPlanObject(value: unknown): Record<string, unknown> {
  return objectValue(value, "canonical plan object");
}

/** Store the exact full plan and bind its immutable address into a V2 revision. */
export function writeProjectRevisionV2Sync(
  input: RevisionWriteInput,
): StoredProjectRevisionV2 {
  const plan = exactPlanObject(input.planObject);
  if (planObjectContentHash(plan) !== input.revision.planContentHash) {
    throw new Error(
      "revision semantic plan hash does not match its exact plan object");
  }
  const storedPlan = writeAuthorityObjectSync(input.paths.objects.plans, plan);
  const revision = parseProjectRevisionV2({
    ...input.revision,
    schemaVersion: 2,
    planObjectHash: storedPlan.hash,
  });
  const storedRevision = writeAuthorityObjectSync(
    input.paths.objects.revisions,
    revision,
  );
  return {
    revision,
    revisionHash: storedRevision.hash,
    planObjectHash: storedPlan.hash,
  };
}

/** V1 remains readable; V2 must reopen the exact plan object it names. */
export function assertRevisionPlanObjectSync(
  paths: ProducerAuthorityPaths,
  revision: ProjectRevision,
): Record<string, unknown> | null {
  if (revision.schemaVersion === 1) return null;
  return exactPlanObject(assertObjectHashSync(
    paths.objects.plans,
    revision.planObjectHash,
  ));
}
