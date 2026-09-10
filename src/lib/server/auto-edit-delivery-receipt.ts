import path from "node:path";
import type { AutoEditJob } from "./auto-edit-job-store";
import {
  writeContentAddressedJsonSync,
  type ContentAddressedJsonResult,
} from "./content-addressed-json";
import {
  resolvedAutoEditDeliveryPolicy,
  type AutoEditDeliveryPolicy,
} from "@/lib/producer/auto-edit-delivery-policy";

export const MP4_ONLY_PROTECTED_BOUNDARIES = [
  "native-primary-selection",
  "cut-checkpoint",
  "plan-checkpoint",
  "revision-checkpoint",
  "render-checkpoint",
  "qc-repair-checkpoint",
  "approved-mirror",
] as const;

export interface AutoEditDeliveryReceiptV2 {
  schemaVersion: 2;
  kind: "auto-edit-delivery-receipt";
  runId: string;
  artifactToken: string;
  requestKey: string;
  deliveryPolicy: AutoEditDeliveryPolicy;
  observedPalmierAdapterCalls: 0;
  observationScope: "render-delivery-adapters";
  legacyLaunchPreflight: "outside-this-receipt";
  protectedBoundaries: typeof MP4_ONLY_PROTECTED_BOUNDARIES;
  finalHash: string;
}

export interface StoredAutoEditDeliveryReceipt extends ContentAddressedJsonResult {
  receipt: AutoEditDeliveryReceiptV2;
}

function receiptValue(job: AutoEditJob): AutoEditDeliveryReceiptV2 {
  if (resolvedAutoEditDeliveryPolicy(job.ctx) !== "mp4-only") {
    throw new Error("zero-Palmier receipt is valid only for MP4-only delivery");
  }
  if (!job.finalHash) {
    throw new Error("MP4-only delivery cannot be receipted without an approved final hash");
  }
  return {
    schemaVersion: 2,
    kind: "auto-edit-delivery-receipt",
    runId: job.token,
    artifactToken: job.artifactToken ?? job.token,
    requestKey: job.requestKey,
    deliveryPolicy: "mp4-only",
    observedPalmierAdapterCalls: 0,
    observationScope: "render-delivery-adapters",
    legacyLaunchPreflight: "outside-this-receipt",
    protectedBoundaries: MP4_ONLY_PROTECTED_BOUNDARIES,
    finalHash: job.finalHash,
  };
}

/** Publish immutable, run/request/final-bound evidence for a successful MP4-only run. */
export function publishAutoEditDeliveryReceiptSync(
  job: AutoEditJob,
): StoredAutoEditDeliveryReceipt {
  const receipt = receiptValue(job);
  const directory = path.join(
    job.ctx.dir,
    ".sniper-auto-edit-delivery-receipts",
  );
  return {
    ...writeContentAddressedJsonSync(directory, receipt),
    receipt,
  };
}
