"""Pure comparison refusal tests; no media or invented performance pass evidence."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from graphics import presenter_layout_geometry
from _presenter_benchmark_comparison import compare_metadata, command_without_alpha
from compare_presenter_1080p import compare_frames
from opening_prefix_contract import PrefixDeadline


def reports() -> tuple[dict, dict, tuple[Path, Path]]:
    """Minimal explicit TEST bookkeeping to exercise metadata guards without processes."""
    roots = (Path("/TEST/old"), Path("/TEST/new"))
    geometry = str(Path(presenter_layout_geometry.__file__).resolve())
    result = []
    for index, root in enumerate(roots):
        commands = [{"stage": label + "-setup", "returncode": 0, "argv": ["/TEST/ffmpeg", str(root / (label + ".media"))]}
                    for label in ("base", "still", "video")]
        commands += [{"stage": label + "-encode", "returncode": 0, "argv": ["/TEST/ffmpeg", "-filter_complex",
            "trim=0" if label == "baseline" else f"trim=0;geq=lum_expr='{index}'[mask]", "-crf", "12", str(root / "out")]}
            for label in ("baseline", "still", "video")]
        references = [{"path": geometry, "sha256": str(index) * 64, "size_bytes": 12},
            {"path": str(root / "still.media"), "sha256": "a" * 64, "size_bytes": 12},
            {"path": "/TEST/ffmpeg", "sha256": "b" * 64, "size_bytes": 12}]
        result.append({"status": "passed" if index else "failed", "cleanup": {"exactGroupsAbsent": True},
            "commands": commands, "references": references, "size": [1920, 1080], "frames": 30,
            "encoder": {"crf": 12}, "frameRate": "30000/1001", "noRetry": True})
    return result[0], result[1], roots


class PresenterBenchmarkComparisonTests(unittest.TestCase):
    """Never accept faster results after changing source content or graph controls."""

    def test_only_mask_expression_may_differ_in_native_command(self) -> None:
        """A crop/scale/preset change cannot hide behind allowed expression caching."""
        old, new, roots = reports()
        self.assertTrue(compare_metadata(old, new, roots)["sameGeneratedInputBytes"])
        new["commands"][-1]["argv"][2] = "scale=64:36;geq=lum_expr='1'[mask]"
        with self.assertRaisesRegex(AssertionError, "non-alpha"):
            compare_metadata(old, new, roots)
        with self.assertRaisesRegex(AssertionError, "mask expressions"):
            command_without_alpha(["-filter_complex", "null"], True)

    def test_input_tool_or_encoder_difference_is_never_autoaccepted(self) -> None:
        """Performance equivalence requires the same actual source bytes and settings."""
        old, new, roots = reports()
        for position in (1, 2):
            changed = copy.deepcopy(new)
            changed["references"][position]["sha256"] = "c" * 64
            with self.assertRaisesRegex(AssertionError, "input, installed tool"):
                compare_metadata(old, changed, roots)
        with self.assertRaisesRegex(AssertionError, "controls/encoder"):
            compare_metadata(old, {**new, "encoder": {"crf": 30}}, roots)

    def test_other_production_code_changes_are_retained_not_silently_dropped(self) -> None:
        """Unrelated legitimate code edits are listed; native command parity still applies."""
        old, new, roots = reports()
        code = Path(presenter_layout_geometry.__file__).resolve().parents[1] / "guided_opening_frames.py"
        new["references"].append({"path": str(code), "sha256": "d" * 64, "size_bytes": 1})
        result = compare_metadata(old, new, roots)
        self.assertEqual(len(result["codeClosureDifferences"]), 2)
        self.assertIn("oldCodeClosure", result)
        self.assertIn("newCodeClosure", result)

    def test_last_encoded_pixel_frame_difference_cannot_be_hidden(self) -> None:
        """A late mismatch fails even when all earlier frames and metadata match."""
        frames = tuple(f"{index:064x}" for index in range(30))
        index = {"encodedOutputs": [{"label": label, "frameHashes": list(frames)}
            for label in ("baseline", "still", "video")], "preencodePrefixOutputs": []}
        report = {"encodes": [{"label": label, "output": {"path": "/TEST/output", "sha256": "a" * 64, "sizeBytes": 1}}
            for label in ("baseline", "still", "video")]}
        changed = (*frames[:-1], "f" * 64)
        with patch("compare_presenter_1080p.verify_held_input"), \
                patch("compare_presenter_1080p._new_frames", side_effect=([frames], [frames], [changed])):
            with self.assertRaisesRegex(AssertionError, "all30 encoded frames differ for video"):
                compare_frames(index, report, Path("/TEST/new"), PrefixDeadline(5))


if __name__ == "__main__":
    unittest.main()
