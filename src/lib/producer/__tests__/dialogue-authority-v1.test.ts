import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  deriveDialogueMapV1,
  parseDialogueMapV1,
  validateDialogueAuthorityV1,
} from "../contracts/dialogue-map-v1";
import { parseDialogueTrackV1 } from "../contracts/dialogue-track-v1";
import { canonicalJsonSha256 } from "../../server/auto-edit-hash";

const fixture = JSON.parse(fs.readFileSync(path.join(
  process.cwd(),
  "scripts/producer/tests/fixtures/dialogue-authority-v1.json",
), "utf8")) as {
  trackHash: string;
  track: Record<string, unknown>;
  map: Record<string, unknown>;
};

const parsed = validateDialogueAuthorityV1(
  fixture.track,
  fixture.map,
  fixture.trackHash,
);
assert.equal(canonicalJsonSha256(parsed.track), fixture.trackHash);
assert.deepEqual(
  deriveDialogueMapV1(parsed.track, fixture.trackHash),
  parsed.dialogueMap,
);
assert.equal(parsed.dialogueMap.totalOutputSamples, 288_000);

const entries = Object.fromEntries(parsed.dialogueMap.entries.map((entry) => [
  entry.dialogueSegmentId,
  entry,
]));
assert.equal(
  entries["dialogue-b-j-handle"]!.normalizedSourceSampleRange.endSampleExclusive,
  entries["dialogue-b-primary"]!.normalizedSourceSampleRange.startSample,
);
assert.equal(
  entries["dialogue-b-primary"]!.normalizedSourceSampleRange.endSampleExclusive,
  entries["dialogue-b-l-handle"]!.normalizedSourceSampleRange.startSample,
);
assert.deepEqual(
  entries["dialogue-c-primary"]!.effectiveSpeed,
  { numerator: "5", denominator: "4" },
);

const floatSpeed = structuredClone(fixture.track);
(
  floatSpeed.segments as Array<Record<string, unknown>>
)[0]!.speed = 1.0;
assert.throws(() => parseDialogueTrackV1(floatSpeed), /PositiveRationalV1/);

const legacyMilliseconds = structuredClone(fixture.track);
(
  legacyMilliseconds.segments as Array<Record<string, unknown>>
)[1]!.audioLeadMs = 100;
assert.throws(
  () => parseDialogueTrackV1(legacyMilliseconds),
  /unsupported fields/,
);

const unordered = structuredClone(fixture.track);
const unorderedSegments = unordered.segments as unknown[];
[unorderedSegments[0], unorderedSegments[1]] = [
  unorderedSegments[1],
  unorderedSegments[0],
];
assert.throws(() => parseDialogueTrackV1(unordered), /canonically ordered/);

const disconnected = structuredClone(fixture.track);
const disconnectedHandle = (
  disconnected.segments as Array<Record<string, unknown>>
)[1]!;
disconnectedHandle.seamSample = Number(disconnectedHandle.seamSample) - 1;
assert.throws(() => parseDialogueTrackV1(disconnected), /declared seam/);

const badClock = structuredClone(fixture.track);
badClock.totalOutputSamples = Number(badClock.totalOutputSamples) - 1;
assert.throws(() => parseDialogueTrackV1(badClock), /B\(total frames\)/);

const badSpeed = structuredClone(fixture.track);
(
  badSpeed.segments as Array<Record<string, unknown>>
)[3]!.speed = { numerator: "6", denominator: "5" };
assert.throws(() => parseDialogueTrackV1(badSpeed), /speed exceeds/);

const staleMap = structuredClone(fixture.map);
const staleRange = (
  staleMap.entries as Array<Record<string, unknown>>
)[2]!.normalizedSourceSampleRange as Record<string, unknown>;
staleRange.endSampleExclusive = Number(staleRange.endSampleExclusive) - 1;
assert.throws(() => parseDialogueMapV1(staleMap), /stale derived/);

const foreignMap = structuredClone(fixture.map);
foreignMap.dialogueTrackHash = "c".repeat(64);
assert.throws(
  () => validateDialogueAuthorityV1(
    fixture.track,
    foreignMap,
    fixture.trackHash,
  ),
  /exactly bind/,
);

console.log("dialogue-authority-v1 tests passed");
