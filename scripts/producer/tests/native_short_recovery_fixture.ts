/** Real-media technical fixture with explicitly synthetic editorial evidence. */
import { copyFileSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileSha256 } from "../../../src/lib/server/auto-edit-hash";
import { writeNativeShortProject } from "../../../src/lib/server/native-short-project";
import { writeNativeAssetOrigin } from "../../../src/lib/server/native-short-asset-origin";
import { fixtureOriginRecord } from "../../../src/lib/server/__tests__/_native-short-origin-fixture";
import {
  nativeShortFixture, refreshNativePacingFixture,
} from "../../../src/lib/server/__tests__/_native-short-project-fixture";

/** Replace inert test assets with real local bytes while retaining explicit TEST scope. */
function realAssets(root: string, dependencies: string[]) {
  const directory = path.join(root, "input");
  mkdirSync(directory);
  let input = nativeShortFixture(directory);
  for (const [index, source] of dependencies.entries()) {
    const asset = input.assets[index], previous = asset.file;
    copyFileSync(source, asset.path);
    asset.sha256 = fileSha256(asset.path)!;
    if (index === 0) asset.file = `assets/${asset.sha256}.mp4`;
    input = JSON.parse(JSON.stringify(input).replaceAll(previous, asset.file));
  }
  return input;
}

/** Author only an explicit two-second compiler/capture/recovery probe, never a production edit. */
function build(root: string, dependencies: string[]) {
  const input = realAssets(root, dependencies);
  input.canvas.title = "TEST Short automatic recovery";
  input.canvas.sourceSize = { w: 320, h: 180 };
  input.canvas.pictureViews[0].crop = [100, 0, 101.25, 180];
  const asset = input.assets[0], origin = fixtureOriginRecord(asset);
  delete asset.origin;
  input.assets[0] = writeNativeAssetOrigin({ asset,
    record: { ...origin.record, sha256: asset.sha256, sizeBytes: statSync(asset.path).size,
      media: { width: 320, height: 180, durationFrames: 60 } },
    acquisition: { ...origin.acquisition, sourceFrameRate: "30/1" },
  }, path.join(root, "TEST-real-media-origin.json"));
  input.canvas.titleCard!.fontSize = 64;
  input.canvas.titleCard!.top = 80;
  // Rebind all synthetic source/origin/pacing/review records after replacing inputs.
  refreshNativePacingFixture(input);
  writeFileSync(path.join(root, "TEST-input.json"), JSON.stringify(input, null, 2), { flag: "wx" });
  const result = writeNativeShortProject(input, path.join(root, "project"));
  writeFileSync(path.join(root, "TEST-fixture.json"), JSON.stringify({
    status: "technical-fixture-authored",
    source: "existing local technical picture and audio excerpt",
    syntheticReview: true,
    productionDelivery: false,
    humanApproved: false,
    directory: result.directory,
    durationSeconds: 2,
  }, null, 2), { flag: "wx" });
}

const [root, ...dependencies] = process.argv.slice(2);
if (!root || dependencies.length !== 5) {
  throw new Error("Expected new root and source, gsap, font, selected JPG, alternate JPG");
}
build(path.resolve(root), dependencies.map(file => path.resolve(file)));
