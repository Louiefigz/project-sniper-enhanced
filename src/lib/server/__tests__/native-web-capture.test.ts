import assert from "node:assert/strict";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileSha256 } from "../auto-edit-hash";
import { assertNativeWebCapture, assertNativeWebCaptureRange } from "../native-web-capture";
import { assembleNativeShortHtml, readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";
import type { NativeAssetBinding } from "../native-short-strategy";

function fixture() {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-web-binding-")));
  const video = path.join(directory, "capture.mp4"), receiptPath = path.join(directory, "capture.json");
  const supervisionPath = path.join(directory, "capture.render.json");
  writeFileSync(video, "synthetic contract data only");
  const sha256 = fileSha256(video)!;
  const receipt = { schemaVersion: 1, kind: "public-web-scroll", status: "captured-for-review", authenticated: false, pageRestyled: false,
    video: { file: "capture.mp4", sha256 }, plan: { duration: 8, fps: 25, url: "https://example.com", allowedHosts: ["example.com"], expectedTitle: "Example", viewport: { width: 540, height: 960, scale: 2 } },
    page: { url: "https://example.com", title: "Example site" }, capture: { fullDecode: "passed", startVisible: true, endVisible: true, observedScrollPixels: 800, frames: 200, fps: 25, width: 1080, height: 1920, nativeResolution: true } };
  const supervision = { startedAt: "2026-09-12T00:00:00Z", status: "public-web-capture-awaiting-editorial-review", output: receiptPath, exitCode: 0,
    cleanup: { verified: true }, leaseCleanupVerified: true, sourceStable: true, sdkStable: true, sandboxStable: true, additionalFilesStable: true };
  const asset: NativeAssetBinding = { file: `assets/${sha256}.mp4`, path: video, sha256, role: "supporting-video" };
  const save = () => {
    writeFileSync(receiptPath, JSON.stringify(receipt)); writeFileSync(supervisionPath, JSON.stringify(supervision));
    asset.webCapture = { path: receiptPath, sha256: fileSha256(receiptPath)!, supervisionPath, supervisionSha256: fileSha256(supervisionPath)! };
  };
  save();
  return { directory, asset, receipt, supervision, save, cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}

test("web capture binding survives actual project assembly/cold read and rejects later receipt mutation", () => {
  const f = fixture();
  try {
    const plan = nativeShortFixture(f.directory); plan.assets.push(f.asset);
    plan.request.mediaPolicy = { placement: "auto", sources: "public-web" };
    plan.extension = { css: "", motion: "", markup: `<video id="web-broll" class="clip" src="${f.asset.file}" data-start="0" data-duration="2" data-media-start="1" muted></video>` };
    plan.strategy.supportingSearch.candidates.push({ assetFile: f.asset.file, sourceStart: 1, sourceEnd: 3,
      observed: "TEST synthetic web scroll", role: "context", claimLimit: "TEST no product-use proof", selected: true,
      reason: "TEST reveal the page", visibleId: "web-broll", startFrame: 0, endFrame: 50 });
    refreshNativePacingFixture(plan);
    const project = writeNativeShortProject(plan, path.join(f.directory, "project"));
    assert.deepEqual(readNativeShortProject(project.directory), plan);
    plan.strategy.supportingSearch.candidates[0].sourceEnd = 9;
    assert.throws(() => assembleNativeShortHtml(plan), /exceeds the frozen/);
    writeFileSync(f.asset.webCapture!.path, "changed receipt");
    assert.throws(() => readNativeShortProject(project.directory), /evidence changed/);
  } finally { f.cleanup(); }
});

test("failed, wrong-page, incomplete and out-of-range recordings cannot be admitted", () => {
  const f = fixture();
  try {
    assert.doesNotThrow(() => assertNativeWebCapture(f.asset));
    assert.throws(() => assertNativeWebCaptureRange(f.asset, 8.1), /exceeds/);
    f.receipt.status = "failed"; f.save(); assert.throws(() => assertNativeWebCapture(f.asset), /incomplete/);
    f.receipt.status = "captured-for-review"; f.receipt.capture.endVisible = false; f.save();
    assert.throws(() => assertNativeWebCapture(f.asset), /incomplete/);
    f.receipt.capture.endVisible = true; f.receipt.page.url = "https://other.example.com"; f.save();
    assert.throws(() => assertNativeWebCapture(f.asset), /identity/);
    f.receipt.page.url = "https://example.com"; f.supervision.cleanup.verified = false; f.save();
    assert.throws(() => assertNativeWebCapture(f.asset), /supervised/);
  } finally { f.cleanup(); }
});
