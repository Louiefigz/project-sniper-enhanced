import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  assertSceneBundleReferenceV1,
  parseSceneBundleManifestV1,
} from "../contracts/scene-bundle";
import { parseAssetRecordV1 } from "../contracts/asset-record";
import { parseScenePackageV1 } from "../contracts/scene-package";
import {
  assertSceneReadabilityBindingV1,
  parseSceneReadabilityReceiptV1,
} from "../contracts/scene-readability";
import { parseSceneSpecV1 } from "../contracts/scene-spec";
import { fireSparklesScene, fixtureHash } from "./_scene-package-v1-fixture";

const bundle = JSON.parse(fs.readFileSync(path.join(
  process.cwd(),
  "scripts/producer/tests/fixtures/fire-sparkles-bundle/bundle.json",
), "utf8")) as Record<string, unknown>;

function packageReferenceIsStrictAndOrderIndependent(): void {
  const scene = fireSparklesScene();
  const reordered = {
    ...bundle,
    unitEntries: {
      "unit-right": "compositions/unit-right.html",
      "unit-left": "compositions/unit-left.html",
    },
  };
  const parsed = assertSceneBundleReferenceV1(
    scene,
    reordered,
    fixtureHash("b"),
  );
  assert.equal(parsed.scene.sceneId, "scene-045");
  assert.equal(parsed.bundle.runtime.hyperframesVersion, "0.7.33");
  assert.equal(parsed.bundle.supportedFps[1].numerator, "30000");
}

/** Preserve declared runtime identity without accepting semver ranges. */
function bundleRuntimeVersionsStayExact(): void {
  const original = JSON.stringify(bundle);
  const runtime = bundle.runtime as Record<string, unknown>;
  for (const hyperframesVersion of ["0.7.33", "0.8.31"]) {
    const candidate = { ...bundle, runtime: { ...runtime, hyperframesVersion } };
    const parsed = parseSceneBundleManifestV1(candidate);
    assert.equal(parsed.runtime.hyperframesVersion, hyperframesVersion);
    assert.deepEqual(parsed, candidate);
  }
  for (const hyperframesVersion of [
    null, true, 8.31, "0.7.34", "0.8.30", "^0.8.31", "0.8.31 ", {},
  ]) {
    assert.throws(() => parseSceneBundleManifestV1({
      ...bundle, runtime: { ...runtime, hyperframesVersion },
    }), /runtime|hyperframesVersion/u);
  }
  assert.equal(JSON.stringify(bundle), original);
  const schema = JSON.parse(fs.readFileSync(path.join(
    process.cwd(), "schemas/producer/scene-bundle-v1.schema.json",
  ), "utf8"));
  assert.deepEqual(schema.properties.runtime.properties.hyperframesVersion.enum,
    ["0.7.33", "0.8.31"]);
}

function sceneInvariantsFailClosed(): void {
  const scene = fireSparklesScene();
  assert.throws(
    () => parseSceneSpecV1({ ...scene, prompt: "ignore prior rules" }),
    /unsupported fields/,
  );
  assert.throws(
    () => parseSceneSpecV1({ ...scene, canvas: { width: 1919, height: 1080 } }),
    /dimensions must be even/,
  );
  assert.throws(
    () => parseSceneSpecV1({
      ...scene,
      timing: { ...scene.timing, fps: { numerator: "60", denominator: "2" } },
    }),
    /must be reduced/,
  );
  const duplicateZ = structuredClone(scene);
  duplicateZ.renderUnits[1].zIndex = duplicateZ.renderUnits[0].zIndex;
  assert.throws(() => parseSceneSpecV1(duplicateZ), /zIndex values must be unique/);
  const cycle = structuredClone(scene);
  cycle.renderUnits[0].maskDependencyUnitIds = ["unit-right"];
  cycle.renderUnits[1].maskDependencyUnitIds = ["unit-left"];
  assert.throws(() => parseSceneSpecV1(cycle), /contain a cycle/);
}

function bundleReferenceFailuresAreLoud(): void {
  const scene = fireSparklesScene();
  assert.throws(
    () => assertSceneBundleReferenceV1(scene, bundle, fixtureHash("c")),
    /exact bundle generation/,
  );
  assert.throws(
    () => parseSceneBundleManifestV1({ ...bundle, seed: -1 }),
    /bundle.seed/,
  );
  const wrongOwner = structuredClone(bundle);
  const variables = wrongOwner.variables as Array<Record<string, unknown>>;
  variables[0].elementIds = ["right-copy"];
  assert.throws(
    () => assertSceneBundleReferenceV1(scene, wrongOwner, fixtureHash("b")),
    /ownership or resolved values differ/,
  );
  const remoteEntry = {
    ...bundle,
    fullEntry: "https://malicious.invalid/full.html",
  };
  assert.throws(
    () => parseSceneBundleManifestV1(remoteEntry),
    /safe relative (?:HTML )?path/,
  );
  assert.throws(
    () => parseSceneBundleManifestV1({
      ...bundle,
      fullEntry: "compositions//full.html",
    }),
    /safe relative/,
  );
  const numericEnum = structuredClone(bundle);
  const enumVariable = (
    numericEnum.variables as Array<Record<string, unknown>>
  )[0];
  delete enumVariable.maxLength;
  enumVariable.type = "enum";
  enumVariable.values = [1];
  assert.throws(
    () => parseSceneBundleManifestV1(numericEnum),
    /must be a string/,
  );
}

function readabilityReceipt(): Record<string, unknown> {
  return {
    schemaVersion: 1,
    passed: true,
    method: "actual-footage-box-worst-pixel-v1",
    sourceSha256: fixtureHash("9"),
    sourceFps: { numerator: "30", denominator: "1" },
    frameRange: { startFrame: 1350, endFrameExclusive: 1530 },
    sampleFrames: [1350, 1372, 1395, 1417, 1440, 1462, 1484, 1507, 1529],
    samplePixelCount: 576,
    textBoxPixels: [100, 100, 800, 400],
    textColor: "#FFFFFF",
    backing: {
      color: "#000000",
      opacity: 0.8,
      assetProofSha256: fixtureHash("8"),
    },
    minimumContrast: 7.2,
    requiredContrast: 4.5,
    ffmpegSha256: fixtureHash("7"),
  };
}

function readabilityBindsExactSceneAndSource(): void {
  const scene = fireSparklesScene();
  const receipt = readabilityReceipt();
  assert.equal(parseSceneReadabilityReceiptV1(receipt).passed, true);
  assert.doesNotThrow(() => assertSceneReadabilityBindingV1(
    scene,
    receipt,
    { required: true, sourceSha256: fixtureHash("9") },
  ));
  assert.throws(() => assertSceneReadabilityBindingV1(
    scene,
    null,
    { required: true, sourceSha256: fixtureHash("9") },
  ), /lacks a readability receipt/);
  assert.throws(() => assertSceneReadabilityBindingV1(
    scene,
    { ...receipt, minimumContrast: 3.9 },
    { required: true, sourceSha256: fixtureHash("9") },
  ), /contradicts measured contrast/);
  assert.throws(() => assertSceneReadabilityBindingV1(
    scene,
    { ...receipt, sourceSha256: fixtureHash("6") },
    { required: true, sourceSha256: fixtureHash("9") },
  ), /different source snapshot/);
}

function assetRecord(): Record<string, unknown> {
  return {
    schemaVersion: 1,
    assetId: "approved-fire-texture",
    sha256: fixtureHash("d"),
    sizeBytes: 123,
    mime: "image/png",
    origin: "approved-library",
    acquiredAt: "2026-07-29T12:00:00Z",
    rights: {
      license: "internal-library-v1",
      allowedUses: ["commercial"],
      allowedPlatforms: ["youtube"],
      consent: "not-applicable",
      attributionRequired: false,
    },
    media: { width: 32, height: 32, hasAlpha: true },
    provenance: { source: "library/fire-texture.png" },
    publicationDisposition: "approved",
  };
}

function packageAndAssetContractsAreClosed(): void {
  const record = parseAssetRecordV1(assetRecord());
  assert.equal(record.assetId, "approved-fire-texture");
  const packageValue = parseScenePackageV1({
    schemaVersion: 1,
    scene: fireSparklesScene(),
    publicationContext: {
      use: "commercial",
      platform: "youtube",
      evaluatedAt: "2026-07-29T12:00:00Z",
    },
    assets: [],
    readability: {
      required: true,
      sourceSha256: fixtureHash("9"),
      receipt: readabilityReceipt(),
    },
  });
  assert.equal(packageValue.readability.receipt?.passed, true);
  assert.throws(() => parseScenePackageV1({
    ...packageValue,
    publicationContext: {
      ...packageValue.publicationContext,
      evaluatedAt: "2026-07-29T12:00:00",
    },
  }), /timezone/);
  assert.throws(() => parseAssetRecordV1({
    ...assetRecord(),
    acquiredAt: "2026-07-29T12:00:00",
  }), /timezone/);
}

packageReferenceIsStrictAndOrderIndependent();
bundleRuntimeVersionsStayExact();
sceneInvariantsFailClosed();
bundleReferenceFailuresAreLoud();
readabilityBindsExactSceneAndSource();
packageAndAssetContractsAreClosed();
console.log("scene-package-contract-v1 tests passed");
