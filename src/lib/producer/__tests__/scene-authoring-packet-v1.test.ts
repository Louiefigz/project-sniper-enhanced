import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { parseSceneAuthoringPacketV1 } from
  "../contracts/scene-authoring-packet";

const hash = (value: string): string => value.repeat(64);

const packet = {
  schemaVersion: 1,
  attemptId: "attempt-scene-045",
  brief: "Blue fire card left; sparkling title card right.",
  sceneAuthority: {
    sceneId: "scene-045",
    timing: {
      startFrame: 1350,
      endFrameExclusive: 1530,
      fps: { numerator: "30", denominator: "1" },
      timelineMapHash: hash("a"),
    },
    durationFrames: 180,
    canvas: { width: 1920, height: 1080 },
    renderMode: "overlay-alpha",
    captionPolicy: "suppress-overlap",
    provenance: {
      origin: "reference-style",
      requestId: "request-fire-sparkles",
      stylePackHash: hash("b"),
    },
  },
  brandTokens: {
    accent: "#054BC9",
    surface: "#07101F",
    cornerRadius: 28,
  },
  approvedAssets: [{
    assetId: "fire-texture",
    sha256: hash("c"),
    mime: "image/png",
    bundleMember: "media/fire.png",
  }],
  examples: [{
    bundleId: "verified-example",
    bundleHash: hash("d"),
  }],
  constraints: {
    hyperframesVersion: "0.7.33",
    declaredVariables: true,
    pausedSeekableTimeline: true,
    rootDuration: true,
    deterministicSeed: true,
    vendoredRuntimeOnly: true,
    renderTimeNetwork: false,
  },
} as const;

const parsed = parseSceneAuthoringPacketV1(packet);
const originalPacket = JSON.stringify(packet);
for (const hyperframesVersion of ["0.7.33", "0.8.31"]) {
  const candidate = {
    ...packet, constraints: { ...packet.constraints, hyperframesVersion },
  };
  assert.deepEqual(parseSceneAuthoringPacketV1(candidate), candidate);
}
for (const hyperframesVersion of [
  null, true, 8.31, "0.7.34", "0.8.30", "^0.8.31", "0.8.31 ", {},
]) {
  assert.throws(() => parseSceneAuthoringPacketV1({
    ...packet, constraints: { ...packet.constraints, hyperframesVersion },
  }), /constraints|hyperframesVersion/u);
}
assert.equal(JSON.stringify(packet), originalPacket);
const schema = JSON.parse(fs.readFileSync(path.join(
  process.cwd(), "schemas/producer/scene-authoring-packet-v1.schema.json",
), "utf8"));
assert.deepEqual(schema.properties.constraints.properties.hyperframesVersion.enum,
  ["0.7.33", "0.8.31"]);
assert.equal(parsed.sceneAuthority.durationFrames, 180);
assert.equal(parsed.approvedAssets[0].bundleMember, "media/fire.png");
assert.throws(() => parseSceneAuthoringPacketV1({
  ...packet,
  sceneAuthority: { ...packet.sceneAuthority, durationFrames: 179 },
}), /disagrees with exact timing/);
assert.throws(() => parseSceneAuthoringPacketV1({
  ...packet,
  constraints: { ...packet.constraints, renderTimeNetwork: true },
}), /released boundary/);
assert.throws(() => parseSceneAuthoringPacketV1({
  ...packet,
  approvedAssets: [{
    ...packet.approvedAssets[0],
    bundleMember: "media//fire.png",
  }],
}), /safe relative path/);

console.log("scene-authoring-packet-v1 tests passed");
