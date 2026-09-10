import path from "node:path";
import type { ProducerReview } from "../auto-edit/review-contract";
import type { SurgicalEditScope } from "@/lib/producer/surgical-edit";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import type { TypedCompatibilityEdit } from "./typed-compatibility-edit";

export const SURGICAL_REVIEW_FILE = ".sniper-surgical-review.json";

export interface SurgicalReviewMarker {
  schemaVersion: 1;
  status: "pending" | "approved";
  scope: SurgicalEditScope;
  planHash?: string;
  changedFields?: string[];
  gateWarnings?: string[];
  critic?: ProducerReview;
  typedCompatibility?: TypedCompatibilityEdit;
}

export function surgicalReviewMarkerPath(dir: string): string {
  return path.join(dir, SURGICAL_REVIEW_FILE);
}

export function writeSurgicalReviewMarker(
  dir: string,
  marker: SurgicalReviewMarker,
): void {
  atomicWriteJsonSync(surgicalReviewMarkerPath(dir), marker);
}

export function beginSurgicalReview(
  dir: string,
  scope: SurgicalEditScope,
): void {
  writeSurgicalReviewMarker(dir, {
    schemaVersion: 1,
    status: "pending",
    scope,
  });
}
