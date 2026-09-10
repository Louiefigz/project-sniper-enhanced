"""Pure/fake-file prefix contract checks, not encoded output qualification."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
from opening_prefix_contract import (CompositorPrefixRequest, HeldPrefixInput, PrefixClock, PrefixDeadline,
    PrefixOracleError, PrefixOracleRuntime, PrefixRanges, validate_request, verify_held_input)
from opening_prefix_oracle import _frames, _graphic_workload


def held(path: Path) -> HeldPrefixInput:
    """TEST fixture captures exact bytes before passing production held-input APIs."""
    path = path.resolve(strict=True)
    return HeldPrefixInput(str(path), hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)


class PrefixContractTests(unittest.TestCase):
    """No semantic or delivery authority is inferred from these byte/clock checks."""

    def test_exact_raw_frame_clock_rejects_missing_extra_shifted_or_wrong_timebase(self) -> None:
        header = "#tb 0: 1001/30000\n"
        row = lambda n: f"0, {n}, {n}, 1, 3456, {'a' * 64}\n"
        valid = header + row(0) + row(1)
        self.assertEqual(_frames(valid, (2, "30000/1001", 3456)), ("a" * 64,) * 2)
        for raw in (header + row(0), valid + row(2), header + row(1) + row(2),
                    valid.replace("1001/30000", "1/30"), valid.replace("3456", "3457")):
            with self.subTest(raw=raw[:30]), self.assertRaises(PrefixOracleError):
                _frames(raw, (2, "30000/1001", 3456))

    def test_hashing_rejects_changed_bytes_links_and_deadline_without_mutating_inputs(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as root:
            path = Path(root) / "input"
            path.write_bytes(b"original")
            row = held(path)
            verify_held_input(row, PrefixDeadline(2))
            path.write_bytes(b"changed!")
            with self.assertRaisesRegex(PrefixOracleError, "changed"):
                verify_held_input(row, PrefixDeadline(2))
            link = Path(root) / "hardlink"
            os.link(path, link)
            with self.assertRaisesRegex(PrefixOracleError, "single-link"):
                verify_held_input(held(path), PrefixDeadline(2))
            with patch("opening_prefix_contract.time.monotonic", side_effect=[1, 3]):
                with self.assertRaisesRegex(PrefixOracleError, "deadline"):
                    verify_held_input(row, PrefixDeadline(1))

    def test_workload_and_unheld_graph_inputs_reject_before_any_process(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as root:
            path = Path(root) / "base"
            path.write_bytes(b"TEST not media")
            source = held(path)
            request = CompositorPrefixRequest(source, (), (), (), PrefixClock("24", 240, 64, 36),
                                              PrefixRanges((0, 24), (0, 48)))
            runtime = PrefixOracleRuntime(source, source, root, 2)
            validate_request(request, runtime)
            invalid = (replace(request, ranges=PrefixRanges((0, 24), (1, 48))),
                replace(request, clock=PrefixClock("24", 10000, 64, 36),
                        ranges=PrefixRanges((0, 24), (0, 3000))),
                replace(request, opening_clips=({"path": "/unheld"},)))
            for value in invalid:
                with self.assertRaises(PrefixOracleError):
                    validate_request(value, runtime)

    def test_aggregate_native_pixel_bound_counts_repeated_decoder_occurrences(self) -> None:
        clock = PrefixClock("24", 240, 1920, 1080)
        clips = tuple({"path": "held"} for _ in range(33))
        request = CompositorPrefixRequest(None, (), clips, clips[:1], clock, PrefixRanges((0, 24), (0, 48)))
        with self.assertRaisesRegex(PrefixOracleError, "aggregate native input"):
            _graphic_workload(request, {"held": {"width": 1920, "height": 1080}})
        result = _graphic_workload(replace(request, full_clips=clips[:30]),
                                   {"held": {"width": 1920, "height": 1080}})
        self.assertFalse(result["fixedProcessRssQualified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
