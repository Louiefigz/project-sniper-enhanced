import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { CompatibilityShadowLock } from
  "./producer-revision-shadow-lock";

export interface CompatibilityShadowBindings {
  manifestHash: string;
  sourceSetHash: string;
  canvasProfileHash: string;
  destinationProfileHashes: string[];
}

/** Preserve the historical synthetic source identity for explicit adoption. */
export function compatibilityShadowBindings(
  parent: Record<string, unknown>,
  lock: CompatibilityShadowLock,
): CompatibilityShadowBindings {
  const sourceSetHash = canonicalJsonSha256({
    kind: "compatibility-source-binding-v1",
    manifestHash: lock.manifestHash,
    transcriptDigest: lock.transcriptDigest,
  });
  const canvasProfileHash = canonicalJsonSha256(parent.target ?? {});
  return {
    manifestHash: lock.manifestHash,
    sourceSetHash,
    canvasProfileHash,
    destinationProfileHashes: [canvasProfileHash],
  };
}
