import assert from "node:assert/strict";
import {
  resolveTimingAnchorV1,
  type AnchorMigrationV1,
} from "../contracts/deferred-request";
import type { TimingAnchorV1 } from "../contracts/timing-anchor";

const oldMap = "a".repeat(64);
const newMap = "b".repeat(64);
const baseMigration: AnchorMigrationV1 = {
  oldTimelineMapHash: oldMap,
  newTimelineMapHash: newMap,
  successors: {},
  segmentVersions: { "segment-old": 2 },
  tombstones: [],
};

function resolve(
  anchor: TimingAnchorV1,
  patch: Partial<AnchorMigrationV1> = {},
) {
  return resolveTimingAnchorV1(anchor, { ...baseMigration, ...patch });
}

const anchors = {
  frame: {
    type: "timeline-frame",
    frame: 1_350,
    timelineMapHash: oldMap,
  },
  transcript: {
    type: "transcript-range",
    startWordId: "word-old-start",
    endWordId: "word-old-end",
    offsetFrames: 2,
  },
  segment: {
    type: "cut-segment",
    segmentId: "segment-old",
    elementVersion: 1,
    basis: "output-frame",
    offsetFrames: 10,
    timelineMapHash: oldMap,
  },
  beat: { type: "semantic-beat", beatId: "beat-old" },
  source: {
    type: "source-time",
    sourceId: "source-old",
    sourceFrame: 120,
    sourceSample: 192_000,
  },
  section: { type: "section", sectionId: "section-old" },
  music: {
    type: "music-beat",
    cueId: "cue-old",
    beatIndex: 4,
    offsetSamples: 32,
  },
} satisfies Record<string, TimingAnchorV1>;

for (const anchor of Object.values(anchors)) {
  assert.equal(resolve(anchor).status, "resolved");
}
const frame = resolve(anchors.frame);
if (frame.status !== "resolved" || frame.anchor.type !== "timeline-frame") {
  throw new Error("expected resolved timeline frame");
}
assert.equal(frame.anchor.frame, 1_350);
assert.equal(frame.anchor.timelineMapHash, newMap);

const rippleCases: Array<{
  anchor: TimingAnchorV1;
  successors: Record<string, string[]>;
  segmentVersions?: Record<string, number>;
}> = [
  {
    anchor: anchors.transcript,
    successors: {
      "word-old-start": ["word-new-start"],
      "word-old-end": ["word-new-end"],
    },
  },
  {
    anchor: anchors.segment,
    successors: { "segment-old": ["segment-new"] },
    segmentVersions: { "segment-new": 2 },
  },
  { anchor: anchors.beat, successors: { "beat-old": ["beat-new"] } },
  { anchor: anchors.source, successors: { "source-old": ["source-new"] } },
  { anchor: anchors.section, successors: { "section-old": ["section-new"] } },
  { anchor: anchors.music, successors: { "cue-old": ["cue-new"] } },
];
for (const entry of rippleCases) {
  assert.equal(resolve(entry.anchor, {
    successors: entry.successors,
    segmentVersions: entry.segmentVersions ?? baseMigration.segmentVersions,
  }).status, "resolved");
}

const splitCases: Array<[TimingAnchorV1, string]> = [
  [anchors.transcript, "word-old-start"],
  [anchors.segment, "segment-old"],
  [anchors.beat, "beat-old"],
  [anchors.source, "source-old"],
  [anchors.section, "section-old"],
  [anchors.music, "cue-old"],
];
for (const [anchor, id] of splitCases) {
  assert.equal(resolve(anchor, {
    successors: { [id]: [`${id}-a`, `${id}-b`] },
  }).status, "ambiguous");
}

const mergeCases = rippleCases.map((entry) => ({
  ...entry,
  successors: Object.fromEntries(
    Object.keys(entry.successors).map((id) => [id, ["merged-child"]]),
  ),
  segmentVersions: entry.anchor.type === "cut-segment"
    ? { "merged-child": 3 } : entry.segmentVersions,
}));
for (const entry of mergeCases) {
  assert.equal(resolve(entry.anchor, {
    successors: entry.successors,
    segmentVersions: entry.segmentVersions ?? baseMigration.segmentVersions,
  }).status, "resolved");
}

const removalCases: Array<[TimingAnchorV1, string]> = [
  [anchors.transcript, "word-old-end"],
  [anchors.segment, "segment-old"],
  [anchors.beat, "beat-old"],
  [anchors.source, "source-old"],
  [anchors.section, "section-old"],
  [anchors.music, "cue-old"],
];
for (const [anchor, id] of removalCases) {
  assert.equal(resolve(anchor, { tombstones: [id] }).status, "dangling");
}
assert.equal(resolve({
  ...anchors.frame,
  timelineMapHash: "c".repeat(64),
}).status, "dangling");

console.log("timing-anchor-migration-matrix tests passed");
