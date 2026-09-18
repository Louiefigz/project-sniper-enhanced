import type { TypedCompatibilityEdit } from "./typed-compatibility-edit";
import {
  runTypedCompatibilityShadowSync,
  type ProducerRevisionShadowResult,
} from "@/lib/server/producer-revision-shadow";

interface ShadowFinalizeInput {
  dir: string;
  manifestPath: string;
  originalPlanText: string;
  parentPlanHash: string;
  request: string;
  requestId?: string;
  submittedAt?: string;
}

interface ShadowCandidate {
  childBytes: Buffer;
  childHash: string;
  typedCompatibility: TypedCompatibilityEdit;
}

export function publishFinalizeRevisionShadow(
  input: ShadowFinalizeInput,
  candidate: ShadowCandidate,
  run = runTypedCompatibilityShadowSync,
): ProducerRevisionShadowResult {
  return run({
    producerDir: input.dir,
    manifestPath: input.manifestPath,
    parentPlanText: input.originalPlanText,
    parentPlanHash: input.parentPlanHash,
    childPlanBytes: candidate.childBytes,
    childPlanHash: candidate.childHash,
    rawIntent: input.request,
    requestId: input.requestId,
    submittedAt: input.submittedAt,
    typedEdit: candidate.typedCompatibility,
  });
}

export type { ProducerRevisionShadowResult };
