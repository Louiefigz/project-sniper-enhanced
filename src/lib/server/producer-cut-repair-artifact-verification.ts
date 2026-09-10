import type { EditBatchV1 } from "@/lib/producer/contracts/edit-batch";
import type { CutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import type { ProjectRevision } from "@/lib/producer/contracts/project-revision";
import { objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { assertContentAddressedFileSync } from "./content-addressed-file";

interface StoredCutRepairVerificationInput {
  paths: ProducerAuthorityPaths;
  hashes: Record<string, string>;
  operation: CutRestoreSpeechV1;
  revision: ProjectRevision;
  invariantProofHash: string;
}
import {
  validateCutRepairPromotion,
  validateCutRepairPromotionByHash,
  type CutRepairPromotionInput,
} from "./producer-cut-repair-artifacts";
import {
  assertObjectHashSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import type { ProducerIdempotencyRecordV1 } from "./producer-revision-store-model";

function requiredHashes(
  record: ProducerIdempotencyRecordV1,
): Record<string, string> {
  const base = [
    "cutRepairCandidate", "cutRepairFragmentReceipt",
    "cutRepairCompositeReceipt", "cutRepairPictureLock",
    "cutRepairSupersession", "captionRepairRevalidation",
    "palmierCutRepairDisposition", "cutRepairInvariantProof",
    "cutRepairPromotionEvidence", "cutRepairFragmentMedia",
    "cutRepairCompositeMedia",
  ];
  const hasRenderedObject =
    typeof record.artifactHashes.cutRepairRenderedCandidate === "string";
  const hasRenderedMedia =
    typeof record.artifactHashes.cutRepairRenderedMedia === "string";
  if (hasRenderedObject !== hasRenderedMedia) {
    throw new Error("stored cut repair rendered artifact set is incomplete");
  }
  const keys = hasRenderedObject
    ? [...base, "cutRepairRenderedCandidate", "cutRepairRenderedMedia"]
    : base;
  return Object.fromEntries(keys.map((key) => [
    key, sha256(record.artifactHashes[key], `stored cut repair ${key}`),
  ]));
}

function reopenedInput(
  paths: ProducerAuthorityPaths,
  hashes: Record<string, string>,
): CutRepairPromotionInput {
  return {
    candidate: objectValue(assertObjectHashSync(
      paths.objects.cutRepairs, hashes.cutRepairCandidate), "stored cut candidate"),
    promotionEvidence: assertObjectHashSync(
      paths.objects.cutRepairs, hashes.cutRepairPromotionEvidence),
  };
}

/** Reopen every P2 object and media hash before recovery advances authority. */
export function verifyStoredCutRepairPromotionSync(
  paths: ProducerAuthorityPaths,
  record: ProducerIdempotencyRecordV1,
  batch: EditBatchV1,
  revision: ProjectRevision,
): void {
  if (batch.stage !== "cut") return;
  const hashes = requiredHashes(record);
  const input = reopenedInput(paths, hashes);
  const validated = validateCutRepairPromotion(
    input, batch, revision, record.invariantProofHash);
  verifyValidated(paths, hashes, validated);
}

function verifyValidated(
  paths: ProducerAuthorityPaths,
  hashes: Record<string, string>,
  validated: ReturnType<typeof validateCutRepairPromotionByHash>,
): void {
  const { parts, fragment, composite, terminal, version, promotion } = validated;
  const expected = {
    cutRepairCandidate: parts.candidate,
    cutRepairFragmentReceipt: parts.fragment,
    cutRepairCompositeReceipt: parts.composite,
    cutRepairPictureLock: parts.pictureLock,
    cutRepairSupersession: parts.supersession,
    captionRepairRevalidation: parts.caption,
    palmierCutRepairDisposition: parts.palmier,
    cutRepairInvariantProof: parts.invariant,
    cutRepairPromotionEvidence: promotion,
    cutRepairFragmentMedia: fragment.sha256,
    cutRepairCompositeMedia: composite.sha256,
    ...(version === 2 ? {
      cutRepairRenderedCandidate: parts.rendered,
      cutRepairRenderedMedia: terminal.sha256,
    } : {}),
  };
  if (Object.entries(expected).some(([key, hash]) => hashes[key] !== hash)) {
    throw new Error("stored cut repair artifact hash set is inconsistent");
  }
  for (const [key, hash] of Object.entries(expected)) {
    if (!key.endsWith("Media")) {
      assertObjectHashSync(paths.objects.cutRepairs, hash);
    }
  }
  assertContentAddressedFileSync(paths.objects.media, fragment.sha256, ".mov");
  assertContentAddressedFileSync(paths.objects.media, composite.sha256, ".mov");
  if (version === 2) {
    assertContentAddressedFileSync(
      paths.objects.media, terminal.sha256, ".mp4");
  }
}

/** Reopen a two-step promotion using its authoritative parsed operation. */
export function verifyStoredCutRepairPromotionByHashesSync(
  input: StoredCutRepairVerificationInput,
): void {
  const { paths, hashes, revision, invariantProofHash } = input;
  const required = requiredHashes({
    artifactHashes: hashes,
  } as ProducerIdempotencyRecordV1);
  const validated = validateCutRepairPromotionByHash(
    reopenedInput(paths, required), input.operation, revision,
    invariantProofHash);
  verifyValidated(paths, required, validated);
}
