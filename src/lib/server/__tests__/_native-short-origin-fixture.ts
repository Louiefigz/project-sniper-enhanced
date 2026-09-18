/** Explicit synthetic v3 fixture authoring; no observations below establish creative quality. */
import { lstatSync, readFileSync } from "node:fs";
import path from "node:path";
import { shortMediaPolicy } from "@/lib/producer/short-direction";
import { writeNativeAssetOrigin, bindNativeWebOrigin } from "../native-short-asset-origin";
import { readNativeAssetOrigin } from "../native-short-asset-use-origins";
import { nativeAssetUseRevisionHash } from "../native-short-asset-use";
import { nativePacingVisualWindows } from "../native-short-pacing-observations";
import type { NativeShortProjectInput } from "../native-short-project";
import type { NativeAssetBinding } from "../native-short-strategy";
import type { NativeAssetUseDecision } from "../native-short-asset-use-types";

/** Source fixture deliberately has eight seconds so outside-dialogue candidates4–5s remain valid. */
function origin(asset: NativeAssetBinding): NativeAssetBinding {
  if (asset.origin) return asset;
  const destination = path.join(path.dirname(asset.path), `${path.basename(asset.file)}.fixture-origin.json`);
  if (asset.webCapture) return bindNativeWebOrigin(asset, destination);
  const image = asset.role === "image";
  return writeNativeAssetOrigin({ asset, record: { schemaVersion: 1, assetId: `test-${asset.sha256.slice(0, 12)}`,
    sha256: asset.sha256, sizeBytes: lstatSync(asset.path).size, mime: image ? "image/png" : "video/mp4", origin: "operator-upload",
    acquiredAt: "2026-09-12T00:00:00Z", rights: { license: "TEST unresolved supplied fixture", allowedUses: ["editorial"],
      allowedPlatforms: ["local-review"], consent: "unknown", attributionRequired: false },
    media: { width: 1920, height: 1080, ...(image ? {} : { durationFrames: 200 }) },
    provenance: { source: asset.path }, publicationDisposition: "needs-review" },
    acquisition: { kind: "provided", accessScope: "operator-private", evidence: [], ...(image ? {} : { sourceFrameRate: "25/1" }) } }, destination);
}

function decision(input: NativeShortProjectInput, index: number): NativeAssetUseDecision {
  const words = input.canvas.occurrences;
  return { id: `test-use-${index}`, decision: "no-insert", purpose: "no-insert",
    speech: { startFrame: 0, endFrame: input.canvas.totalFrames, occurrenceIds: words.map(word => word[0]), text: words.map(word => word[5]).join(" ") },
    entity: { name: "TEST illustrative source", role: "none", canonicalIdentity: null },
    reason: "TEST explicitly authored fixture choice", rejectedAlternative: "TEST no incidental cutaway",
    claimLimit: "TEST structural fixture does not establish a real result", context: "TEST entire retained context",
    inspection: { method: "not-reviewed", observations: [], limitations: ["TEST synthetic data; source and playback not inspected"] }, selection: null };
}

function insertedDecisions(input: NativeShortProjectInput): NativeAssetUseDecision[] {
  const markup = input.extension?.markup ?? "", windows = nativePacingVisualWindows(input, markup);
  return [...markup.matchAll(/<(img|video)\b[^>]*>/gu)].map((match, index) => {
    const tag = match[0], id = /\sid="([^"]+)"/u.exec(tag)?.[1], file = /\ssrc="([^"]+)"/u.exec(tag)?.[1];
    const asset = input.assets.find(row => row.file === file), window = windows.find(row => row.id === id);
    if (!asset || !window || !id) throw new Error("TEST intended insert lacks fixture source/window");
    const receipt = readNativeAssetOrigin(asset), row = decision(input, index), video = match[1] === "video";
    const start = Number(/\sdata-media-start="([^"]+)"/u.exec(tag)?.[1]);
    const [num, den] = input.canvas.frameRate.split("/").map(Number);
    row.decision = "insert"; row.purpose = "illustrate";
    row.selection = { assetFile: asset.file, targetId: id, startFrame: window.startFrame, endFrame: window.endFrame, kind: video ? asset.webCapture ? "web" : "video" : "image",
      essentialRegion: [0, 0, receipt.record.media.width!, receipt.record.media.height!], essentialContent: "TEST full source frame",
      audio: video ? "muted" : "none", sourceIdentity: receipt.record.provenance.source, attribution: null,
      ...(video ? { sourceRange: { startSeconds: start, endSeconds: start + (window.endFrame - window.startFrame) * den / num,
        frameRate: receipt.acquisition.sourceFrameRate! } } : {}) };
    return row;
  });
}

/** Reauthor the test's origins and decisions only after its intended canvas/request mutation. */
export function refreshNativeAssetUseFixture(input: NativeShortProjectInput): void {
  input.assets = input.assets.map(asset => ["source", "supporting-video", "image"].includes(asset.role) ? origin(asset) : asset);
  const decisions = insertedDecisions(input);
  input.strategy.schemaVersion = 3;
  input.strategy.assetUse = { schemaVersion: 1, revisionHash: nativeAssetUseRevisionHash(input), policy: shortMediaPolicy(input.request),
    intendedUse: { use: "editorial", platform: "local-review" }, decisions: decisions.length ? decisions : [decision(input, 0)] };
}

/** Read exact synthetic receipt data for intentional corruption tests. */
export function fixtureOriginRecord(asset: NativeAssetBinding) {
  return JSON.parse(readFileSync(asset.origin!.path, "utf8"));
}
