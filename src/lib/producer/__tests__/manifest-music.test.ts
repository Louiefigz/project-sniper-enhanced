import assert from "node:assert/strict";
import {
  requireSourceSetAdmission,
  summarizeManifestMusic,
  type AssetManifest,
  type ManifestAsset,
} from "../types";

assert.deepEqual(summarizeManifestMusic(undefined), {
  project: 0,
  bundled: 0,
  available: 0,
});

const assets: ManifestAsset[] = [
  { id: "music-1", path: "/project/music/theme.wav", source: "library" },
  { id: "music-2", path: "/repo/assets/music/default-bed.mp3", source: "builtin" },
  // Legacy project manifests did not always carry source; never call those bundled.
  { id: "music-3", path: "/project/music/legacy.mp3" },
];
assert.deepEqual(summarizeManifestMusic(assets), {
  project: 2,
  bundled: 1,
  available: 3,
});

const receiptSha256 = "a".repeat(64);
const admitted = {
  sourceSetAdmission: {
    schemaVersion: 1,
    receiptPath: `.sniper-source-sets/${receiptSha256}.json`,
    receiptSha256,
    sourceSetDigest: "b".repeat(64),
    entryCount: 3,
  },
} as AssetManifest;
assert.equal(requireSourceSetAdmission(admitted).entryCount, 3);
assert.throws(
  () => requireSourceSetAdmission({} as AssetManifest),
  /no source-set admission binding/,
);
assert.throws(
  () => requireSourceSetAdmission({
    ...admitted,
    sourceSetAdmission: { ...admitted.sourceSetAdmission!, receiptPath: "../receipt.json" },
  }),
  /binding is malformed/,
);

console.log("manifest-music.test.ts: all assertions passed");
