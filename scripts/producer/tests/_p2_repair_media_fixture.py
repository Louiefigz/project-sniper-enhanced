"""Shared real-media fixtures for P2 repair execution tests."""
from __future__ import annotations

import os
import shutil
import subprocess

from edit.exact_timing import ProjectClock
from edit.repair_fragment_contracts import RepairMediaTools
from fingerprints import file_sha256

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def tools() -> RepairMediaTools:
    """Return realpath- and byte-pinned local FFmpeg tools."""
    ffmpeg = os.path.realpath(str(FFMPEG))
    ffprobe = os.path.realpath(str(FFPROBE))
    return RepairMediaTools(
        ffmpeg, file_sha256(ffmpeg), ffprobe, file_sha256(ffprobe))


def media(path: str, fps: str, source: bool,
          vfr: bool | None = None) -> None:
    """Create a 150-frame source or exact-PCM normalized parent."""
    video = f"testsrc2=s=160x90:r={fps}:d=8" if source \
        else f"color=c=blue:s=160x90:r={fps}:d=8"
    audio = ("sine=frequency=880:duration=8:sample_rate=48000"
             if source else "anullsrc=r=48000:cl=stereo")
    command = [
        str(FFMPEG), "-y", "-v", "error",
        "-f", "lavfi", "-i", video,
        "-f", "lavfi", "-i", audio,
    ]
    if source and vfr is not False:
        command.extend([
            "-vf", "select='not(eq(mod(n,5),1))'",
            "-fps_mode", "vfr",
        ])
    command.extend([
        "-frames:v", "150", "-c:v", "libx264",
        "-crf", "18", "-pix_fmt", "yuv420p",
    ])
    if source:
        command.extend([
            "-shortest", "-c:a", "aac", "-ar", "48000", "-ac", "2",
        ])
    else:
        numerator, denominator = (int(term) for term in fps.split("/"))
        samples = 150 * 48_000 * denominator // numerator
        command.extend([
            "-af", f"atrim=end_sample={samples}",
            "-c:a", "pcm_s32le", "-ar", "48000", "-ac", "2",
        ])
    subprocess.run([*command, path], check=True)


def operation(clock: ProjectClock) -> dict[str, object]:
    """Return one valid multi-source audio-only repair operation."""
    dirty_start = clock.sample_at_frame(60)
    extension_samples = 2_400
    extension_frames = clock.containing_frame(extension_samples - 1) + 1
    return {
        "schemaVersion": 1,
        "operation": "cut.restoreSpeech",
        "target": {
            "kind": "word-range", "sourceId": "source-b",
            "wordIds": ["w-" + "1" * 16], "occurrence": 1,
            "sourceSampleRange": {
                "startSample": 48_000, "endSampleExclusive": 52_800},
            "transcriptTimingHash": "a" * 64,
        },
        "parentPictureLockHash": "b" * 64,
        "parentTimelineMapHash": "c" * 64,
        "segment": {
            "segmentId": "segment-b", "elementVersion": 1, "edge": "end"},
        "sourceExtension": {
            "startSample": 50_400, "endSampleExclusive": 52_800},
        "sourceSampleRate": 48_000,
        "speed": {"numerator": "1", "denominator": "1"},
        "extensionFrames": extension_frames,
        "preserveUnrelated": True,
        "totalOutputFramesBefore": 150,
        "totalOutputFramesAfter": 150,
        "method": "audio-lj-overlap",
        "pictureDirtyWindows": [],
        "audioDirtyWindows": [{
            "startFrame": 60,
            "endFrameExclusive": 60 + extension_frames}],
        "audioDirtySampleRanges": [{
            "startSample": dirty_start,
            "endSampleExclusive": dirty_start + extension_samples,
        }],
        "replacedAudioSampleRanges": [{
            "startSample": dirty_start,
            "endSampleExclusive": dirty_start + extension_samples,
        }],
        "replaceableAudioEvidenceHash": "d" * 64,
        "extensionOutputSamples": extension_samples,
        "unchangedPictureMappingRanges": [{
            "startFrame": 0, "endFrameExclusive": 150}],
        "revalidatedDependentIds": ["dialogue-b"],
        "unchangedDependentIds": ["scene-a"],
    }


def picture_operation(clock: ProjectClock) -> dict[str, object]:
    """Return one valid picture-changing duration-neutral repair."""
    item = operation(clock)
    dirty = {"startFrame": 50, "endFrameExclusive": 80}
    dirty_samples = {
        "startSample": clock.sample_at_frame(50),
        "endSampleExclusive": clock.sample_at_frame(80),
    }
    removed = clock.sample_at_frame(52) - clock.sample_at_frame(50)
    for key in ("replacedAudioSampleRanges",
                "replaceableAudioEvidenceHash"):
        item.pop(key)
    item.update({
        "method": "extend-and-reclaim-silence",
        "pictureDirtyWindows": [dirty],
        "audioDirtyWindows": [dirty],
        "audioDirtySampleRanges": [dirty_samples],
        "reclaimedSilence": {
            "silenceId": "silence-a",
            "sourceSampleRange": {
                "startSample": 12_000,
                "endSampleExclusive": 15_200,
            },
            "outputFrameRange": {
                "startFrame": 50,
                "endFrameExclusive": 52,
            },
        },
        "sourceVideoFrameRange": {
            "startFrame": 31,
            "endFrameExclusive": 33,
        },
        "sourceFrameRate": clock.fps.to_dict(),
        "quantizationResidualSamples": removed - 2_400,
        "residualPolicy": "reclaimed-proved-silence",
        "unchangedPictureMappingRanges": [
            {"startFrame": 0, "endFrameExclusive": 50},
            {"startFrame": 80, "endFrameExclusive": 150},
        ],
    })
    return item
