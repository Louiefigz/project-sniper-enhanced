"""Terminal B(F) and outside-closure media evidence for P2 candidates."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from edit.exact_timing import PositiveRational, ProjectClock
from edit.picture_lock_common import content_hash
from edit.repair_composite import (
    RepairCompositeRequest,
    render_repair_composite,
)
from edit.repair_fragment import render_repair_fragment
from edit.repair_fragment_contracts import (
    RepairFragmentRequest,
    RepairRenderError,
)
from tests._p2_repair_media_fixture import (
    FFMPEG,
    FFPROBE,
    media,
    operation,
    picture_operation,
    tools,
)

RATES = tuple(PositiveRational(*terms) for terms in (
    (24000, 1001), (24, 1), (25, 1), (30000, 1001),
    (30, 1), (50, 1), (60000, 1001), (60, 1),
))


def _schema() -> dict[str, object]:
    path = (Path(__file__).resolve().parents[3] / "schemas" / "producer"
            / "cut-repair-composite-receipt-v1.schema.json")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _request(root: str, rate: PositiveRational,
             picture: bool = False,
             dirty_start: int | None = None) -> RepairCompositeRequest:
    fps = f"{rate.numerator}/{rate.denominator}"
    parent = os.path.join(root, "parent.mov")
    source = os.path.join(root, "source.mov")
    fragment = os.path.join(root, "fragment.mov")
    candidate = os.path.join(root, "candidate.mov")
    media(parent, fps, False)
    media(source, fps, True, False if picture else None)
    clock = ProjectClock(rate, 48_000)
    action = picture_operation(clock) if picture else operation(clock)
    if dirty_start is not None:
        dirty_end = dirty_start + action["extensionFrames"]
        start_sample = clock.sample_at_frame(dirty_start)
        samples = {
            "startSample": start_sample,
            "endSampleExclusive":
                start_sample + action["extensionOutputSamples"],
        }
        action["audioDirtyWindows"] = [{
            "startFrame": dirty_start,
            "endFrameExclusive": dirty_end,
        }]
        action["audioDirtySampleRanges"] = [samples]
        action["replacedAudioSampleRanges"] = [samples]
    receipt = render_repair_fragment(RepairFragmentRequest(
        action, content_hash(action), parent, source, fragment, clock, tools()))
    return RepairCompositeRequest(
        parent, fragment, candidate, receipt, content_hash(action),
        clock, tools())


def _assert_shape(case: unittest.TestCase,
                  value: dict[str, object]) -> None:
    schema = _schema()
    case.assertEqual(set(value), set(schema["required"]))
    case.assertEqual(set(value), set(schema["properties"]))
    for key in ("clock", "inputs", "output", "outsideDirtyOracle", "tools"):
        child = schema["properties"][key]
        case.assertEqual(set(value[key]), set(child["required"]))
        case.assertEqual(set(value[key]), set(child["properties"]))


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe required")
class RepairTerminalCompositeTests(unittest.TestCase):
    def test_terminal_pcm_matches_b_f_at_every_released_rate(self) -> None:
        for rate in RATES:
            with self.subTest(rate=rate):
                with tempfile.TemporaryDirectory(
                        prefix="p2-terminal-") as directory:
                    root = os.path.realpath(directory)
                    request = _request(root, rate)
                    receipt = render_repair_composite(request)
                    expected = request.clock.sample_at_frame(150)
                    self.assertEqual(
                        receipt["terminalExpectedSamples"], expected)
                    self.assertEqual(
                        receipt["output"]["audioSamplesPerChannel"], expected)
                    self.assertEqual(receipt["output"]["videoFrames"], 150)
                    self.assertEqual(
                        receipt["clock"]["fps"], rate.to_dict())
                    self.assertTrue(
                        receipt["outsideDirtyOracle"]["pictureMatches"])
                    self.assertEqual(
                        receipt["outsideDirtyOracle"]["pictureScope"],
                        "full-program")
                    self.assertTrue(
                        receipt["outsideDirtyOracle"]["pcmMatches"])
                    _assert_shape(self, receipt)

    def test_early_middle_and_terminal_repairs_build_full_candidates(self) -> None:
        rate = PositiveRational(30, 1)
        for dirty_start in (0, 60, 148):
            with self.subTest(dirty_start=dirty_start):
                with tempfile.TemporaryDirectory(
                        prefix="p2-position-") as directory:
                    request = _request(
                        os.path.realpath(directory), rate,
                        dirty_start=dirty_start)
                    receipt = render_repair_composite(request)
                    self.assertEqual(receipt["output"]["videoFrames"], 150)
                    self.assertEqual(
                        receipt["output"]["audioSamplesPerChannel"], 240_000)
                    self.assertTrue(
                        receipt["outsideDirtyOracle"]["pictureMatches"])
                    self.assertTrue(
                        receipt["outsideDirtyOracle"]["pcmMatches"])

    def test_picture_repair_preserves_media_outside_dirty_window(self) -> None:
        rate = PositiveRational(30000, 1001)
        with tempfile.TemporaryDirectory(
                prefix="p2-picture-terminal-") as directory:
            request = _request(os.path.realpath(directory), rate, True)
            receipt = render_repair_composite(request)
            self.assertEqual(
                receipt["dirtyFrameRange"],
                {"startFrame": 50, "endFrameExclusive": 80})
            self.assertTrue(receipt["outsideDirtyOracle"]["pictureMatches"])
            self.assertEqual(
                receipt["outsideDirtyOracle"]["pictureScope"],
                "outside-dirty")
            self.assertTrue(receipt["outsideDirtyOracle"]["pcmMatches"])

    def test_compositor_rehashes_media_instead_of_trusting_receipt(self) -> None:
        rate = PositiveRational(30, 1)
        with tempfile.TemporaryDirectory(
                prefix="p2-terminal-tamper-") as directory:
            request = _request(os.path.realpath(directory), rate)
            receipt = {
                **request.fragment_receipt,
                "output": {
                    **request.fragment_receipt["output"],
                    "sha256": "0" * 64,
                },
            }
            tampered = RepairCompositeRequest(
                request.parent_path, request.fragment_path,
                request.output_path, receipt, request.operation_hash,
                request.clock, request.tools)
            with self.assertRaisesRegex(
                    RepairRenderError, "does not bind media bytes"):
                render_repair_composite(tampered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
