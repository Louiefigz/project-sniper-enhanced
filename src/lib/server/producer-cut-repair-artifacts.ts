import { lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import type { EditBatchV1 } from "@/lib/producer/contracts/edit-batch";
import {
  parseCutRestoreSpeechV1,
  type CutRestoreSpeechV1,
} from "@/lib/producer/contracts/cut-restore-speech-v1";
import type { ProjectRevision } from "@/lib/producer/contracts/project-revision";
import { objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { writeContentAddressedFileSync } from "./content-addressed-file";
import {
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import { validateCutRepairPromotionEvidence } from
  "./producer-cut-repair-promotion-evidence";
import { validateCutRepairCandidateV1 } from
  "./producer-cut-repair-candidate-v1";
import { validateCutRepairCandidateV2 } from
  "./producer-cut-repair-candidate-v2";

export interface CutRepairPromotionInput {
  candidate: unknown;
  promotionEvidence: unknown;
}

export interface ValidatedCutRepairPromotion {
  candidate: Record<string, unknown>;
  parts: Record<string, string>;
  fragment: { path: string; sha256: string };
  composite: { path: string; sha256: string };
  terminal: { path: string; sha256: string };
  version: 1 | 2;
  promotion: string;
}
interface MediaProof { path: string; sha256: string }
interface StoredPromotion {
  candidate: Record<string, unknown>; fragment: MediaProof;
  composite: MediaProof;
  terminal?: MediaProof;
  version?: 1 | 2;
}
type PromotionStoreInput = {
  paths: ProducerAuthorityPaths; producerDir: string; batch: EditBatchV1;
  input: CutRepairPromotionInput | undefined;
  revision: ProjectRevision; invariantProofHash: string;
};
type PromotionHashStoreInput =
  Omit<PromotionStoreInput, "batch" | "input">
  & { input: CutRepairPromotionInput; operation: CutRestoreSpeechV1 };

function assertStagedMedia(producerDir: string, mediaPath: string): void {
  const root = path.join(producerDir, ".sniper-cut-repair-staging");
  const lexical = path.resolve(mediaPath);
  if (lexical !== mediaPath || !lexical.startsWith(`${root}${path.sep}`)) {
    throw new Error("cut repair media must come from controller-owned staging");
  }
  const stat = lstatSync(mediaPath);
  if (!stat.isFile() || stat.isSymbolicLink() || realpathSync(mediaPath) !== lexical) {
    throw new Error("cut repair staged media must be a canonical regular file");
  }
}

/** Recompute every cross-runtime binding without trusting caller hashes. */
export function validateCutRepairPromotion(
  input: CutRepairPromotionInput | undefined,
  batch: EditBatchV1,
  revision: ProjectRevision,
  invariantProofHash: string,
): ValidatedCutRepairPromotion {
  if (!input || batch.stage !== "cut" || batch.operations.length !== 1) {
    throw new Error("cut repair commit requires one Python-owned proof envelope");
  }
  const operation = parseCutRestoreSpeechV1(batch.operations[0].action);
  return validateCutRepairPromotionByHash(
    input, operation, revision, invariantProofHash);
}

export function validateCutRepairPromotionByHash(
  input: CutRepairPromotionInput | undefined,
  operationValue: unknown,
  revision: ProjectRevision,
  invariantProofHash: string,
): ValidatedCutRepairPromotion {
  if (!input) throw new Error(
    "cut repair promotion requires one Python-owned proof envelope");
  const operation = parseCutRestoreSpeechV1(operationValue);
  const actionHash = canonicalJsonSha256(operation);
  const candidate = objectValue(input.candidate, "cut repair candidate");
  const validated = candidate.schemaVersion === 2
    ? {
      candidate,
      ...validateCutRepairCandidateV2(
        candidate, actionHash, revision, invariantProofHash),
      version: 2 as const,
    }
    : validateCutRepairCandidateV1(
      candidate, actionHash, revision, invariantProofHash);
  const promotion = validateCutRepairPromotionEvidence(
    input.promotionEvidence, operation, validated.terminal.sha256);
  if (revision.authoritativeSidecars.cutRepairPromotionEvidence !== promotion) {
    throw new Error("cut repair revision does not bind promotion evidence");
  }
  return { ...validated, promotion };
}

function promotionObjects(
  input: CutRepairPromotionInput,
  candidate: Record<string, unknown>,
): Record<string, unknown> {
  return {
    cutRepairCandidate: candidate,
    cutRepairFragmentReceipt: candidate.fragmentReceipt,
    cutRepairCompositeReceipt: candidate.compositeReceipt,
    cutRepairPictureLock: candidate.childPictureLock,
    cutRepairSupersession: candidate.supersessionReceipt,
    captionRepairRevalidation: candidate.captionRevalidation,
    palmierCutRepairDisposition: candidate.palmierDisposition,
    cutRepairInvariantProof: candidate.invariantProof,
    cutRepairPromotionEvidence: input.promotionEvidence,
    ...(candidate.schemaVersion === 2
      ? { cutRepairRenderedCandidate: candidate.renderedCandidate } : {}),
  };
}

function storeValidatedPromotion(
  paths: ProducerAuthorityPaths,
  producerDir: string,
  input: CutRepairPromotionInput,
  validated: StoredPromotion,
): Record<string, string> {
  const { candidate, fragment, composite } = validated;
  assertStagedMedia(producerDir, fragment.path);
  assertStagedMedia(producerDir, composite.path);
  if (validated.version === 2 && validated.terminal) {
    assertStagedMedia(producerDir, validated.terminal.path);
  }
  const objects = promotionObjects(input, candidate);
  const stored = Object.fromEntries(Object.entries(objects).map(
    ([key, value]) => [
      key, writeAuthorityObjectSync(paths.objects.cutRepairs, value).hash,
    ],
  ));
  writeContentAddressedFileSync(paths.objects.media, fragment.path, fragment.sha256, ".mov");
  writeContentAddressedFileSync(
    paths.objects.media, composite.path, composite.sha256, ".mov");
  const result = {
    ...stored,
    cutRepairFragmentMedia: fragment.sha256,
    cutRepairCompositeMedia: composite.sha256,
  };
  if (candidate.schemaVersion === 2 && validated.terminal) {
    writeContentAddressedFileSync(
      paths.objects.media,
      validated.terminal.path,
      validated.terminal.sha256,
      ".mp4",
    );
    return {
      ...result,
      cutRepairRenderedMedia: validated.terminal.sha256,
    };
  }
  return result;
}

export function storeCutRepairPromotionSync(
  value: PromotionStoreInput,
): Record<string, string> {
  const { paths, producerDir, input, batch, revision, invariantProofHash } = value;
  if (batch.stage !== "cut") return {};
  if (!input) throw new Error(
    "cut repair commit requires one Python-owned proof envelope");
  return storeValidatedPromotion(paths, producerDir, input,
    validateCutRepairPromotion(input, batch, revision, invariantProofHash));
}

export function storeCutRepairPromotionByHashSync(
  value: PromotionHashStoreInput,
): Record<string, string> {
  const {
    paths, producerDir, input, operation, revision, invariantProofHash,
  } = value;
  const validated = validateCutRepairPromotionByHash(
    input, operation, revision, invariantProofHash);
  return storeValidatedPromotion(paths, producerDir, input, validated);
}
