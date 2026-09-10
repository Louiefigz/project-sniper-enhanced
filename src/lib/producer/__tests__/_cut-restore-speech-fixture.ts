export const fixtureSha = (value: string): string => value.repeat(64);

export function cutRestoreAction(
  pictureLockHash = fixtureSha("2"),
  timelineMapHash = fixtureSha("e"),
): Record<string, unknown> {
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    target: {
      kind: "word-range",
      sourceId: "raw-1",
      wordIds: ["w-1111111111111111"],
      occurrence: 1,
      sourceSampleRange: {
        startSample: 48_000,
        endSampleExclusive: 52_800,
      },
      transcriptTimingHash: fixtureSha("d"),
    },
    parentPictureLockHash: pictureLockHash,
    parentTimelineMapHash: timelineMapHash,
    segment: { segmentId: "seg-0001", elementVersion: 1, edge: "end" },
    sourceExtension: {
      startSample: 50_400,
      endSampleExclusive: 52_800,
    },
    sourceSampleRate: 48_000,
    speed: { numerator: "1", denominator: "1" },
    extensionFrames: 2,
    preserveUnrelated: true,
    totalOutputFramesBefore: 360,
    totalOutputFramesAfter: 360,
    method: "audio-lj-overlap",
    pictureDirtyWindows: [],
    audioDirtyWindows: [{ startFrame: 45, endFrameExclusive: 47 }],
    audioDirtySampleRanges: [{
      startSample: 72_000,
      endSampleExclusive: 74_400,
    }],
    replacedAudioSampleRanges: [{
      startSample: 72_000,
      endSampleExclusive: 74_400,
    }],
    replaceableAudioEvidenceHash: fixtureSha("a"),
    extensionOutputSamples: 2_400,
    unchangedPictureMappingRanges: [{
      startFrame: 0,
      endFrameExclusive: 360,
    }],
    revalidatedDependentIds: ["dialogue-1"],
    unchangedDependentIds: ["scene-1"],
  };
}
