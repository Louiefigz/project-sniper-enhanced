import assert from "node:assert/strict";
import { summarizeManifestMusic, type ManifestAsset } from "../types";

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

console.log("manifest-music.test.ts: all assertions passed");
