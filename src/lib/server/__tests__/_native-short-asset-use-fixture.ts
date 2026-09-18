/** Synthetic origin and use fixtures; they establish no source identity or image quality. */
import { lstatSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { buildNativeCanvas } from "../native-short-composition";
import { fileSha256 } from "../auto-edit-hash";
import { nativeAssetUseRevisionHash } from "../native-short-asset-use";
import type { NativeAssetOriginReceipt, NativeAssetUseDecision, NativeAssetUseInput, NativeAssetUseOptions } from "../native-short-asset-use-types";
import { nativeShortFixture } from "./_native-short-project-fixture";

export function assetDecision(): NativeAssetUseDecision {
  return { id: "test-use", decision: "no-insert", speech: { startFrame: 0, endFrame: 50, occurrenceIds: [0, 1], text: "Test words." },
    entity: { name: "TEST speaker", role: "none", canonicalIdentity: null }, purpose: "no-insert",
    reason: "TEST retain speaker performance", rejectedAlternative: "TEST incidental noun does not merit a cutaway",
    claimLimit: "TEST no product claim", context: "TEST full synthetic sentence retained",
    inspection: { method: "not-reviewed", observations: [], limitations: ["TEST synthetic fixtures are not visual reviews"] }, selection: null };
}

export function assetUseFixture() {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-asset-use-")));
  const input: NativeAssetUseInput = nativeShortFixture(directory);
  const options: NativeAssetUseOptions = { required: true, expectedPolicy: { placement: "auto", sources: "local-only" } };
  const receipts = new Map<string, NativeAssetOriginReceipt>();
  input.strategy.assetUse = { schemaVersion: 1, revisionHash: "", policy: options.expectedPolicy,
    intendedUse: { use: "editorial", platform: "local-review" }, decisions: [assetDecision()] };
  const saveOrigin = (asset: NativeAssetUseInput["assets"][number]) => {
    const file = path.join(directory, `${path.basename(asset.file)}.origin.json`);
    writeFileSync(file, JSON.stringify(receipts.get(asset.file)));
    asset.origin = { path: file, sha256: fileSha256(file)! };
  };
  const addOrigin = (asset: NativeAssetUseInput["assets"][number]) => {
    receipts.set(asset.file, { schemaVersion: 1, kind: "native-short-asset-origin", assetFile: asset.file,
      record: { schemaVersion: 1, assetId: `test-${receipts.size}`, sha256: asset.sha256,
        sizeBytes: lstatSync(asset.path).size, mime: asset.role === "image" ? "image/png" : "video/mp4", origin: "operator-upload",
        acquiredAt: "2026-09-12T00:00:00Z", rights: { license: "TEST unresolved operator supplied record", allowedUses: ["editorial"],
          allowedPlatforms: ["local-review"], consent: "unknown", attributionRequired: false },
        media: { width: 1080, height: 1920, ...(asset.role === "image" ? {} : { durationFrames: 50 }) },
        provenance: { source: asset.path }, publicationDisposition: "needs-review" },
      acquisition: { kind: "provided", accessScope: "operator-private", evidence: [], ...(asset.role === "image" ? {} : { sourceFrameRate: "25/1" }) } });
    saveOrigin(asset);
  };
  addOrigin(input.assets[0]);
  const refresh = () => { input.strategy.assetUse!.revisionHash = nativeAssetUseRevisionHash(input); };
  const addMedia = (kind: "image" | "video" = "image") => {
    const file = path.join(directory, `insert.${kind === "image" ? "png" : "mp4"}`);
    writeFileSync(file, `TEST synthetic ${kind} bytes`);
    const asset: NativeAssetUseInput["assets"][number] = { file: `assets/${path.basename(file)}`, path: file,
      sha256: fileSha256(file)!, role: kind === "image" ? "image" : "supporting-video" };
    input.assets.push(asset); addOrigin(asset);
    const tag = kind === "image" ? "img" : "video";
    input.extension = { css: "", motion: "", markup: `<${tag} id="test-insert" class="clip" src="${asset.file}" data-start="0" data-duration="2"${kind === "video" ? ' data-media-start="0" muted' : ""}></${tag}>` };
    const decision = input.strategy.assetUse!.decisions[0];
    decision.decision = "insert"; decision.purpose = "illustrate";
    decision.selection = { assetFile: asset.file, targetId: "test-insert", kind, startFrame: 0, endFrame: 50,
      essentialRegion: [0, 0, 1080, 1920], essentialContent: "TEST synthetic image region", audio: kind === "image" ? "none" : "muted",
      sourceIdentity: asset.path, attribution: null,
      ...(kind === "video" ? { sourceRange: { startSeconds: 0, endSeconds: 2, frameRate: "25/1" } } : {}) };
    refresh(); return asset;
  };
  const makePublic = (asset: NativeAssetUseInput["assets"][number]) =>
    makePublicAsset({ input, directory, receipts, saveOrigin, refresh }, asset);
  refresh();
  return { input, directory, options, receipts, saveOrigin, refresh, addMedia, makePublic,
    html: () => buildNativeCanvas(input.canvas) + (input.extension?.markup ?? "") + (input.extension?.css ?? ""),
    cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}
function makePublicAsset(context: {
  input: NativeAssetUseInput; directory: string; receipts: Map<string, NativeAssetOriginReceipt>;
  saveOrigin: (asset: NativeAssetUseInput["assets"][number]) => void; refresh: () => void;
}, asset: NativeAssetUseInput["assets"][number]): void {
  const { input, directory, receipts, saveOrigin, refresh } = context;
    const receipt = receipts.get(asset.file)!;
    const evidence = path.join(directory, "source-evidence.txt");
    writeFileSync(evidence, "TEST original source metadata only; no source review occurred");
    receipt.acquisition = { kind: "public-download", accessScope: "public", evidence: [{ path: evidence, sha256: fileSha256(evidence)! }], ...(asset.role === "image" ? {} : { sourceFrameRate: "25/1" }) };
    receipt.record.origin = "reference-derived"; receipt.record.provenance.source = "https://example.com/original";
    input.strategy.assetUse!.decisions[0].selection!.sourceIdentity = receipt.record.provenance.source;
    saveOrigin(asset); refresh();
}

export type AssetUseFixture = ReturnType<typeof assetUseFixture>;
export function withAssetUse(run: (fixture: AssetUseFixture) => void): void {
  const fixture = assetUseFixture();
  try { run(fixture); } finally { fixture.cleanup(); }
}
