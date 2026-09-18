/** Admit frozen website B-roll with its acquisition and resource-owner receipts. */
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileSha256 } from "./auto-edit-hash";
import type { NativeAssetBinding } from "./native-short-strategy";

export interface NativeWebCaptureBinding {
  path: string; sha256: string;
  supervisionPath: string; supervisionSha256: string;
}

function pinnedJson(file: string, hash: string) {
  if (!path.isAbsolute(file) || realpathSync(file) !== file || !/^[a-f0-9]{64}$/u.test(hash)
      || fileSha256(file) !== hash) throw new Error("Web capture evidence changed or is not canonical");
  return JSON.parse(readFileSync(file, "utf8"));
}

/** Structural provenance admission; human visual judgment is recorded separately. */
export function assertNativeWebCapture(asset: NativeAssetBinding): void {
  const binding = asset.webCapture;
  if (!binding) return;
  const receipt = pinnedJson(binding.path, binding.sha256);
  const supervision = pinnedJson(binding.supervisionPath, binding.supervisionSha256);
  const capture = receipt.capture;
  if (asset.role !== "supporting-video" || receipt.schemaVersion !== 1 || receipt.kind !== "public-web-scroll"
      || receipt.status !== "captured-for-review" || receipt.authenticated !== false || receipt.pageRestyled !== false
      || receipt.video?.sha256 !== asset.sha256 || receipt.video.file !== path.basename(asset.path)
      || path.dirname(binding.path) !== path.dirname(asset.path) || path.dirname(binding.supervisionPath) !== path.dirname(asset.path)
      || capture?.fullDecode !== "passed" || capture.startVisible !== true || capture.endVisible !== true
      || capture.nativeResolution !== true || capture.fps !== receipt.plan.fps || ![25, 30].includes(capture.fps)
      || capture.width !== receipt.plan.viewport.width * receipt.plan.viewport.scale
      || capture.height !== receipt.plan.viewport.height * receipt.plan.viewport.scale
      || !Number.isFinite(capture.observedScrollPixels) || Math.abs(capture.observedScrollPixels) < 80
      || !Number.isSafeInteger(capture.frames) || capture.frames !== Math.round(receipt.plan.duration * receipt.plan.fps)) {
    throw new Error("Web B-roll is incomplete or differs from its frozen capture");
  }
  if (supervision.status !== "public-web-capture-awaiting-editorial-review" || supervision.output !== binding.path
      || supervision.exitCode !== 0 || supervision.cleanup?.verified !== true || supervision.leaseCleanupVerified !== true
      || supervision.sourceStable !== true || supervision.sdkStable !== true || supervision.sandboxStable !== true
      || supervision.additionalFilesStable !== true) throw new Error("Web capture lacks a successful supervised acquisition");
  const requested = new URL(receipt.plan.url), actual = new URL(receipt.page.url);
  if (requested.protocol !== "https:" || actual.protocol !== "https:" || requested.username || requested.password
      || actual.username || actual.password || !receipt.plan.allowedHosts.includes(actual.hostname)
      || !receipt.page.title.toLowerCase().includes(receipt.plan.expectedTitle.toLowerCase())) {
    throw new Error("Web capture lost its verified public page identity");
  }
}

/** A selected clip cannot outlast the captured source or relabel it as source audio. */
export function assertNativeWebCaptureRange(asset: NativeAssetBinding, sourceEnd: number): void {
  if (!asset.webCapture) return;
  assertNativeWebCapture(asset);
  const receipt = pinnedJson(asset.webCapture.path, asset.webCapture.sha256);
  if (sourceEnd > receipt.capture.frames / receipt.capture.fps + .00001) {
    throw new Error("Selected web B-roll range exceeds the frozen recording");
  }
}
