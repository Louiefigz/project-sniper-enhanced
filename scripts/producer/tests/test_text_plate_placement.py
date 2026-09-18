"""Held placement and actual compositing-order attribution regressions."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from audit import audit_composite_visual as composite
from audit.audit_frames import FrameRef
from audit.audit_text_placement import (
    PlateContext, binding_error, cropped_samples, observe_placements,
)


def graphic(start: float = 0) -> dict:
    """Small synthetic graphic; the sidecar is not a render approval."""
    return {"kind": "section-marker", "anchor": "free-band", "outStart": start,
            "outEnd": 3, "spec": {"readability": "plates"}}


def row(entry: dict) -> dict:
    """Explicit test-only placement observation matching its candidate."""
    return {key: entry[key] for key in ("kind", "anchor", "outStart", "outEnd")} | {
        "canvas": [480, 853], "placedBBox": [10, 20, 100, 200]}


def fixture(root: Path) -> tuple:
    """Create regular evidence files without invoking or claiming a decoder."""
    plan = {"graphicsTrack": [graphic()]}
    (root / "edit_plan.json").write_text(json.dumps(plan))
    (root / "graphics_placements.json").write_text(json.dumps([row(graphic())]))
    for name in ("base_final.mp4", "final.mp4"):
        (root / name).write_bytes(b"synthetic-identity-only-not-media")
    return plan, str(root / "base_final.mp4")


class TextPlatePlacementBindingTests(unittest.TestCase):
    def test_missing_and_foreign_observation_fail_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, reference = fixture(root)
            evidence = root / "graphics_placements.json"
            evidence.unlink()
            self.assertTrue(observe_placements(temporary, plan, reference).error)
            self.assertFalse(evidence.exists())
            evidence.write_text(json.dumps([row(graphic(1))]))
            held = evidence.read_bytes()
            foreign = observe_placements(temporary, plan, reference)
            self.assertIn("different graphic/window/order", foreign.error)
            self.assertEqual(evidence.read_bytes(), held)

    def test_held_documents_and_media_cannot_change_during_measurement(self) -> None:
        for name in ("graphics_placements.json", "edit_plan.json", "final.mp4", "base_final.mp4"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                plan, reference = fixture(root)
                context = observe_placements(temporary, plan, reference)
                self.assertEqual(binding_error(context), "")
                path = root / name
                path.write_bytes(path.read_bytes() + b" ")
                self.assertIn("changed during measurement", binding_error(context))


class TextPlateExecutedOrderTests(unittest.TestCase):
    def context(self, entries: list) -> PlateContext:
        """Use equal synthetic pixels solely to exercise the ordering gate."""
        image = Image.new("RGB", (480, 853))
        return PlateContext(rows=[row(item) for item in entries], graphics=entries,
            samples=[("hold", 1.5, (image, image))], error="")

    def test_earlier_background_is_not_mistaken_for_foreground_occlusion(self) -> None:
        # Candidate index0 executes above index1 because its start is later.
        context = self.context([graphic(1), graphic(0)])
        self.assertEqual(len(cropped_samples(0, context)), 1)

    def test_later_start_occludes_even_when_it_has_an_earlier_candidate_index(self) -> None:
        context = self.context([graphic(1), graphic(0)])
        with self.assertRaisesRegex(ValueError, "later/above"):
            cropped_samples(1, context)

    def test_equal_start_uses_stable_candidate_order(self) -> None:
        context = self.context([graphic(), graphic()])
        with self.assertRaisesRegex(ValueError, "later/above"):
            cropped_samples(0, context)
        self.assertEqual(len(cropped_samples(1, context)), 1)

    def test_each_matching_final_base_pair_is_decoded_once_for_all_kinds(self) -> None:
        image = Image.new("RGB", (10, 10))
        for kind in ("section-marker", "statement-card"):
            final = {"graphic0_mid": FrameRef("graphic0_mid", "graphic", 1.25, "final.jpg")}
            base = {"graphic0_mid": FrameRef("graphic0_mid", "graphic", 1.25, "base.jpg")}
            entry = {**graphic(), "kind": kind}
            with patch.object(composite, "_paired_images", return_value=(image, image)) as decode:
                composite._graphic_results({"graphicsTrack": [entry]}, final, base)
            decode.assert_called_once_with("final.jpg", "base.jpg")


if __name__ == "__main__":
    unittest.main()
