"""P2 media-boundary and early/middle/late preservation evidence."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
)
from edit.picture_lock_common import content_hash
from edit.picture_lock_mapping import (
    MappingProofInput,
    MappingSpan,
    prove_unchanged_mapping,
)
from edit.repair_composite import (
    RepairCompositeRequest,
    render_repair_composite,
)
from edit.repair_fragment import render_repair_fragment
from edit.repair_fragment_contracts import RepairFragmentRequest
from tests._p2_repair_media_fixture import (
    FFMPEG,
    FFPROBE,
    media as _media,
    operation as _operation,
    picture_operation as _picture_operation,
    tools as _tools,
)


def _raw_video(path: str, start: int, end: int) -> bytes:
    command = [
        str(FFMPEG), "-v", "error", "-i", path,
        "-vf", f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS",
        "-pix_fmt", "yuv420p", "-f", "rawvideo", "-",
    ]
    return subprocess.run(command, check=True, capture_output=True).stdout


def _raw_audio(path: str, start: int, end: int) -> bytes:
    command = [
        str(FFMPEG), "-v", "error", "-i", path,
        "-af", f"atrim=start_sample={start}:end_sample={end}",
        "-ar", "48000", "-ac", "2", "-f", "s32le", "-",
    ]
    return subprocess.run(command, check=True, capture_output=True).stdout


def _source_44100(path: str) -> None:
    command = [
        str(FFMPEG), "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=8",
        "-f", "lavfi", "-i",
        "sine=frequency=880:duration=8:sample_rate=44100",
        "-frames:v", "150", "-shortest", "-c:v", "libx264",
        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-ar", "44100", "-ac", "2", path,
    ]
    subprocess.run(command, check=True)


def _operation_44100(
    clock: ProjectClock,
    source_start: int,
    dirty_frame: int,
) -> dict[str, object]:
    operation = _operation(clock)
    source_end = source_start + 2_940
    dirty_start = clock.sample_at_frame(dirty_frame)
    dirty_end = clock.sample_at_frame(dirty_frame + 2)
    operation["target"]["sourceSampleRange"] = {
        "startSample": source_start,
        "endSampleExclusive": source_end,
    }
    operation["sourceExtension"] = {
        "startSample": source_start,
        "endSampleExclusive": source_end,
    }
    operation["sourceSampleRate"] = 44_100
    operation["extensionFrames"] = 2
    operation["extensionOutputSamples"] = dirty_end - dirty_start
    operation["audioDirtyWindows"] = [{
        "startFrame": dirty_frame,
        "endFrameExclusive": dirty_frame + 2,
    }]
    samples = {
        "startSample": dirty_start,
        "endSampleExclusive": dirty_end,
    }
    operation["audioDirtySampleRanges"] = [samples]
    operation["replacedAudioSampleRanges"] = [samples]
    return operation


def _picture_at(
    clock: ProjectClock,
    dirty_start: int,
) -> dict[str, object]:
    operation = _picture_operation(clock)
    dirty_end = dirty_start + 30
    dirty = {
        "startFrame": dirty_start,
        "endFrameExclusive": dirty_end,
    }
    operation["pictureDirtyWindows"] = [dirty]
    operation["audioDirtyWindows"] = [dirty]
    operation["audioDirtySampleRanges"] = [{
        "startSample": clock.sample_at_frame(dirty_start),
        "endSampleExclusive": clock.sample_at_frame(dirty_end),
    }]
    operation["reclaimedSilence"]["outputFrameRange"] = {
        "startFrame": dirty_start,
        "endFrameExclusive": dirty_start + 2,
    }
    removed = clock.sample_at_frame(dirty_start + 2) \
        - clock.sample_at_frame(dirty_start)
    operation["quantizationResidualSamples"] = removed - 2_400
    operation["unchangedPictureMappingRanges"] = [
        *([{"startFrame": 0, "endFrameExclusive": dirty_start}]
          if dirty_start else []),
        *([{"startFrame": dirty_end, "endFrameExclusive": 150}]
          if dirty_end < 150 else []),
    ]
    return operation


def _mapping_proof(dirty_start: int) -> tuple[dict, str]:
    dirty_end = dirty_start + 30
    parent = (
        MappingSpan(
            FrameRange(0, 150), "source-a", SampleRange(0, 240_000)),
    )
    child: list[MappingSpan] = []
    if dirty_start:
        child.append(MappingSpan(
            FrameRange(0, dirty_start),
            "source-a",
            SampleRange(0, dirty_start * 1_600),
        ))
    child.append(MappingSpan(
        FrameRange(dirty_start, dirty_end),
        "source-b",
        SampleRange(20_000, 50_000),
    ))
    if dirty_end < 150:
        child.append(MappingSpan(
            FrameRange(dirty_end, 150),
            "source-a",
            SampleRange(dirty_end * 1_600, 240_000),
        ))
    return prove_unchanged_mapping(MappingProofInput(
        "c" * 64, "e" * 64, parent, tuple(child),
        (FrameRange(dirty_start, dirty_end),), 150))


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe required")
class RepairExitMatrixTests(unittest.TestCase):
    def test_audio_repair_preserves_every_parent_picture_frame(self) -> None:
        rate = PositiveRational(24000, 1001)
        clock = ProjectClock(rate, 48_000)
        with tempfile.TemporaryDirectory(prefix="p2-preserve-") as directory:
            root = os.path.realpath(directory)
            parent = os.path.join(root, "parent.mov")
            source = os.path.join(root, "source.mov")
            output = os.path.join(root, "repair.mov")
            fps = f"{rate.numerator}/{rate.denominator}"
            _media(parent, fps, False)
            _media(source, fps, True)
            operation = _operation(clock)
            receipt = render_repair_fragment(RepairFragmentRequest(
                operation, content_hash(operation), parent, source,
                output, clock, _tools()))
            frames = operation["audioDirtyWindows"][0]
            length = frames["endFrameExclusive"] - frames["startFrame"]
            self.assertEqual(
                _raw_video(parent, frames["startFrame"],
                           frames["endFrameExclusive"]),
                _raw_video(output, 0, length))
            replacement = operation["extensionOutputSamples"]
            output_samples = receipt["output"]["audioSamplesPerChannel"]
            parent_start = clock.sample_at_frame(frames["startFrame"])
            self.assertEqual(
                _raw_audio(parent, parent_start + replacement,
                           parent_start + output_samples),
                _raw_audio(output, replacement, output_samples))

    def test_picture_repairs_preserve_retained_frames_and_mapping(self) -> None:
        rate = PositiveRational(30000, 1001)
        clock = ProjectClock(rate, 48_000)
        with tempfile.TemporaryDirectory(prefix="p2-positions-") as directory:
            root = os.path.realpath(directory)
            parent = os.path.join(root, "parent.mov")
            source = os.path.join(root, "source.mov")
            fps = f"{rate.numerator}/{rate.denominator}"
            _media(parent, fps, False)
            _media(source, fps, True, False)
            for index, start in enumerate((0, 50, 120)):
                with self.subTest(start=start):
                    operation = _picture_at(clock, start)
                    output = os.path.join(root, f"repair-{index}.mov")
                    receipt = render_repair_fragment(RepairFragmentRequest(
                        operation, content_hash(operation), parent, source,
                        output, clock, _tools()))
                    proof, proof_hash = _mapping_proof(start)
                    self.assertRegex(proof_hash, r"^[0-9a-f]{64}$")
                    self.assertEqual(
                        proof["authorizedDirtyWindows"],
                        operation["pictureDirtyWindows"])
                    self.assertEqual(receipt["output"]["videoFrames"], 30)
                    self.assertEqual(
                        _raw_video(parent, start + 2, start + 30),
                        _raw_video(output, 0, 28))

    def test_adjacent_44100_repairs_share_one_48000_boundary(self) -> None:
        clock = ProjectClock(PositiveRational(30, 1), 48_000)
        with tempfile.TemporaryDirectory(prefix="p2-44100-") as directory:
            root = os.path.realpath(directory)
            parent = os.path.join(root, "parent.mov")
            source = os.path.join(root, "source-44100.mov")
            _media(parent, "30/1", False)
            _source_44100(source)
            normalized: list[dict[str, int]] = []
            for index, (source_start, frame) in enumerate((
                    (44_100, 60), (47_040, 80))):
                operation = _operation_44100(clock, source_start, frame)
                output = os.path.join(root, f"repair-{index}.mov")
                candidate = os.path.join(root, f"candidate-{index}.mov")
                receipt = render_repair_fragment(RepairFragmentRequest(
                    operation, content_hash(operation), parent, source,
                    output, clock, _tools()))
                composite = render_repair_composite(RepairCompositeRequest(
                    parent, output, candidate, receipt,
                    content_hash(operation), clock, _tools()))
                normalized.append(
                    receipt["retime"]["normalizedSourceSampleRange"])
                self.assertEqual(
                    receipt["output"]["audioSamplesPerChannel"], 3_200)
                self.assertEqual(
                    composite["output"]["audioSamplesPerChannel"],
                    clock.sample_at_frame(150))
            self.assertEqual(
                normalized[0]["endSampleExclusive"],
                normalized[1]["startSample"])
