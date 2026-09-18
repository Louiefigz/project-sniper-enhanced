import assert from "node:assert/strict";
import { closeSync, ftruncateSync, openSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { readNativeAssetOrigin } from "../native-short-asset-use-origins";
import { fileSha256 } from "../auto-edit-hash";
import { assertNativeShortAssetUse, nativeShortAssetUseReport } from "../native-short-asset-use";
import { withAssetUse, type AssetUseFixture } from "./_native-short-asset-use-fixture";

const check = (f: AssetUseFixture) => assertNativeShortAssetUse(f.input, f.html(), f.options);

function webCapture(f: AssetUseFixture) {
  const asset = f.addMedia("video"); f.makePublic(asset);
  const origin = f.receipts.get(asset.file)!;
  const receiptPath = path.join(f.directory, "capture.json"), supervisionPath = path.join(f.directory, "capture.render.json");
  const receipt = { schemaVersion: 1, kind: "public-web-scroll", status: "captured-for-review", authenticated: false, pageRestyled: false,
    video: { file: path.basename(asset.path), sha256: asset.sha256 },
    plan: { duration: 2, fps: 25, url: "https://example.com/original", allowedHosts: ["example.com"], expectedTitle: "Example", viewport: { width: 540, height: 960, scale: 2 } },
    page: { url: "https://example.com/original", title: "Example site" },
    capture: { fullDecode: "passed", startVisible: true, endVisible: true, observedScrollPixels: 800, frames: 50, fps: 25, width: 1080, height: 1920, nativeResolution: true } };
  const supervision = { status: "public-web-capture-awaiting-editorial-review", output: receiptPath, exitCode: 0,
    cleanup: { verified: true }, leaseCleanupVerified: true, sourceStable: true, sdkStable: true, sandboxStable: true, additionalFilesStable: true };
  writeFileSync(receiptPath, JSON.stringify(receipt)); writeFileSync(supervisionPath, JSON.stringify(supervision));
  asset.webCapture = { path: receiptPath, sha256: fileSha256(receiptPath)!, supervisionPath, supervisionSha256: fileSha256(supervisionPath)! };
  origin.acquisition.kind = "public-web-capture"; origin.acquisition.webCapture = { ...asset.webCapture };
  f.input.strategy.assetUse!.decisions[0].selection!.kind = "web";
  f.options.expectedPolicy.sources = "public-web"; f.saveOrigin(asset); f.refresh();
  return { asset, origin };
}

test("source restrictions apply equally to external stills and videos", () => withAssetUse(f => {
  const asset = f.addMedia(); f.makePublic(asset);
  assert.throws(() => check(f), /source restriction/);
  f.options.expectedPolicy.sources = "provided-only"; assert.throws(() => check(f), /source restriction/);
  f.options.expectedPolicy.sources = "public-web"; check(f);
  f.input.assets.pop(); f.input.extension = undefined;
  const video = f.addMedia("video"); f.makePublic(video);
  f.options.expectedPolicy.sources = "local-only"; assert.throws(() => check(f), /source restriction/);
}));

test("origin and acquisition evidence cannot be removed, mutated or downgraded", () => withAssetUse(f => {
  const { asset, origin } = webCapture(f); check(f);
  delete asset.webCapture; f.refresh(); assert.throws(() => check(f), /original acquisition/);
  asset.webCapture = origin.acquisition.webCapture;
  delete asset.origin; f.refresh(); assert.throws(() => check(f), /immutable origin receipt/);
  f.saveOrigin(asset); f.refresh();
  writeFileSync(origin.acquisition.evidence[0].path, "TEST changed after acquisition");
  assert.throws(() => check(f), /origin evidence.*changed/);
}));

test("web source receipts retain stronger checks and all native-export pins", () => withAssetUse(f => {
  const { asset, origin } = webCapture(f); check(f);
  const report = nativeShortAssetUseReport(f.input, f.html(), f.options);
  assert.equal(report.originEvidenceFiles.length, 5);
  assert.ok(report.originEvidenceFiles.some(row => row.path === asset.webCapture!.supervisionPath));
  origin.acquisition.kind = "provided"; origin.record.origin = "operator-upload";
  f.saveOrigin(asset); f.refresh(); assert.throws(() => check(f), /cannot be relabeled/);
}));

test("prepared requests independently constrain assets labeled as provided", () => withAssetUse(f => {
  const asset = f.addMedia();
  f.input.requestPacket = { path: path.join(f.directory, "request.json"), sha256: "a".repeat(64) }; f.refresh();
  assert.throws(() => check(f), /supplied media inventory/);
  f.options.providedAssets = [{ file: f.input.canvas.sourceFile, sha256: f.input.assets[0].sha256 }];
  assert.throws(() => check(f), /absent from the prepared request/);
  f.options.providedAssets.push({ file: asset.file, sha256: asset.sha256 }); check(f);
}));

test("shared rights remain restrictive without upgrading unknown consent or disposition", () => withAssetUse(f => {
  const asset = f.addMedia(), origin = f.receipts.get(asset.file)!; check(f);
  origin.record.publicationDisposition = "blocked"; f.saveOrigin(asset); f.refresh();
  assert.throws(() => check(f), /blocked or expired/);
  origin.record.publicationDisposition = "needs-review";
  origin.record.rights.allowedPlatforms = ["youtube"]; f.saveOrigin(asset); f.refresh();
  assert.throws(() => check(f), /intended local review/);
  origin.record.rights.allowedPlatforms = ["local-review"];
  origin.record.rights.expiresAt = "2000-01-01T00:00:00Z"; f.saveOrigin(asset); f.refresh();
  assert.throws(() => check(f), /blocked or expired/);
}));

test("source identity, acquisition kind and timebase cannot be replaced by assertion flags", () => withAssetUse(f => {
  const asset = f.addMedia("video"), origin = f.receipts.get(asset.file)!;
  f.input.strategy.assetUse!.decisions[0].selection!.sourceRange!.frameRate = "60/1";
  assert.throws(() => check(f), /speed-1/);
  f.input.strategy.assetUse!.decisions[0].selection!.sourceRange!.frameRate = "25/1";
  origin.acquisition.kind = "local-library"; f.saveOrigin(asset); f.refresh();
  assert.throws(() => check(f), /contradicts.*origin/);
  origin.acquisition.kind = "provided"; Object.assign(origin.acquisition, { verified: true });
  f.saveOrigin(asset); f.refresh(); assert.throws(() => check(f), /unsupported fields.*verified/);
}));

test("origin reader rejects acquisition contradictions before an asset enters a plan", () => withAssetUse(f => {
  const asset = f.addMedia(), origin = f.receipts.get(asset.file)!;
  origin.acquisition.kind = "public-download"; f.saveOrigin(asset);
  assert.throws(() => readNativeAssetOrigin(asset), /Public acquisition requires/);
}));

test("receipt and evidence bounds reject oversized files before their hash can be checked", () => withAssetUse(f => {
  const asset = f.addMedia(), origin = f.receipts.get(asset.file)!;
  const evidence = path.join(f.directory, "oversized-evidence.bin");
  const descriptor = openSync(evidence, "w"); ftruncateSync(descriptor, 16 * 1024 ** 2 + 1); closeSync(descriptor);
  origin.acquisition.evidence = [{ path: evidence, sha256: "a".repeat(64) }]; f.saveOrigin(asset);
  assert.throws(() => readNativeAssetOrigin(asset), /bounded regular-file size/);
  const receipt = openSync(asset.origin!.path, "w"); ftruncateSync(receipt, 512 * 1024 + 1); closeSync(receipt);
  assert.throws(() => readNativeAssetOrigin(asset), /bounded regular-file size/);
}));
