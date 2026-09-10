import fs from "fs";
import path from "path";
import type { ProjectJson } from "@/app/api/_lib/workspace";
import {
  previewAuthorityInvalidated,
  readApproval,
} from "@/lib/server/auto-edit-quality-artifacts";
import { autoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import {
  qualityPolicyRequirement,
  readQualityPolicyMarker,
} from "@/lib/server/auto-edit-quality-policy";
import { reconcileIntentCapabilities } from "@/lib/producer/intent-capabilities";
import type { ProjectIntent } from "@/lib/producer/intent-presets";
import type { AssetManifest } from "@/lib/producer/types";

interface IntentStatus {
  intent: ProjectIntent | null;
  requestedIntent: ProjectIntent | null;
  intentDecisions: NonNullable<ProjectJson["intentDecisions"]>;
}

/** Preview a legacy capability migration for the card; GET never writes project.json. */
export function projectedIntentStatus(
  project: ProjectJson | null,
  manifestPath: string | null,
): IntentStatus {
  const stored = {
    intent: project?.resolvedIntent ?? project?.intent ?? null,
    requestedIntent: project?.requestedIntent ?? project?.intent ?? null,
    intentDecisions: project?.intentDecisions ?? [],
  };
  if (!project || !manifestPath || !stored.requestedIntent) {
    return stored;
  }
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as AssetManifest;
    const resolution = reconcileIntentCapabilities(stored.requestedIntent, manifest);
    return {
      intent: resolution.resolvedIntent ?? null,
      requestedIntent: resolution.requestedIntent,
      intentDecisions: resolution.decisions,
    };
  } catch {
    return stored;
  }
}

export function approvedFinal(producerDir: string): boolean {
  if (!fs.existsSync(path.join(producerDir, "final.mp4"))) return false;
  if (previewAuthorityInvalidated(producerDir)) return false;
  const policy = qualityPolicyRequirement(producerDir);
  if (policy.legacy) return true;
  if (!policy.valid) return false;
  try {
    const marker = readQualityPolicyMarker(producerDir);
    const approval = readApproval(producerDir);
    if (marker?.mode !== "managed" || marker.ctx.dir !== producerDir || !approval) return false;
    const authority = autoEditAuthoritySnapshot(marker.ctx);
    return approval.authorityDigest === authority.digest
      && approval.planHash === authority.planHash
      && approval.manifestHash === authority.manifestHash;
  } catch {
    return false;
  }
}
