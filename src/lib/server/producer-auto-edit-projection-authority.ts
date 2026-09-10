import {
  parseProjectionReceiptV1,
  type ProjectionReceiptV1,
} from "@/lib/producer/contracts/projection-receipt";
import type { CompatibilityTimelineProjectionV1 } from
  "@/app/api/producer/auto-edit/compatibility-timeline-projection";
import { canonicalJsonSha256 } from "./auto-edit-hash";

interface AutoEditProjectionInput {
  planContentHash: string;
  manifestHash: string;
  sourceSnapshotSetHash: string;
  projection: CompatibilityTimelineProjectionV1;
}

/** Wrap the compatibility payload in the canonical revision receipt schema. */
export function autoEditProjectionReceipt(
  input: AutoEditProjectionInput,
): ProjectionReceiptV1 {
  const projectionHash = canonicalJsonSha256(input.projection);
  return parseProjectionReceiptV1({
    schemaVersion: 1,
    canonicalPlanHash: input.planContentHash,
    manifestHash: input.manifestHash,
    sourceSnapshotSetHash: input.sourceSnapshotSetHash,
    compilerHash: input.projection.compilerHash,
    timelineMapHash: input.projection.timelineMapHash,
    projectionHash,
    generationPath: `compatibility_projections/${projectionHash}.json`,
  });
}
