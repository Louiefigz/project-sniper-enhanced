"""Actual catalog-source preflight with TEST-only plans, no sealed/media launch."""
from __future__ import annotations

import copy
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import digest
from guided_graphic_template import inspect_full_program_graphics, read_graphic_template
from guided_opening_inputs import OpeningInputs
from test_guided_body_frames import fixture, rebind


def valid_inputs(count: int = 12) -> OpeningInputs:
    """Give every TEST statement 90 real frames, preserving all full-program bindings."""
    inputs = fixture(count)
    docs = inputs.documents
    for index, entry in enumerate(docs["candidatePlan"]["graphicsTrack"]):
        entry["spec"]["variant"] = "classic"
        row = docs["frameBindings"]["graphics"][index]
        end = row["startFrame"] + 90
        row["endFrameExclusive"] = docs["occurrences"]["anchors"][f"e-{index}"] = end
        entry["outEnd"] = float(Fraction(end, 1) / Fraction(docs["authority"]["frameRate"]))
    rebind(inputs)
    return inputs


class GuidedBodyTemplateTests(unittest.TestCase):
    """Fail before source sealing/spawn; a valid template is not rendered proof."""

    def test_real_template_rules_cover_all_twelve_rows_and_complete_crossing_animation(self) -> None:
        inputs = valid_inputs()
        inputs.documents["authority"]["review"]["endFrameExclusive"] = 85
        before = copy.deepcopy(inputs.documents)
        result = inspect_full_program_graphics(inputs, lambda: None)
        self.assertEqual(len(result["graphics"]), 12)
        self.assertEqual(result["graphics"][0]["fullAnimationFrames"], 90)
        self.assertEqual(result["graphics"][0]["endFrameExclusive"], 91)
        self.assertFalse(result["bodyRendered"])
        self.assertFalse(result["deliveryApproved"])
        self.assertEqual(inputs.documents, before)

    def test_late_short_card_blocks_before_any_seal_or_render(self) -> None:
        inputs = valid_inputs()
        docs = inputs.documents
        row = docs["frameBindings"]["graphics"][-1]
        row["endFrameExclusive"] = docs["occurrences"]["anchors"]["e-11"] = row["startFrame"] + 30
        docs["candidatePlan"]["graphicsTrack"][-1]["outEnd"] = float(
            Fraction(row["endFrameExclusive"], 1) / Fraction(docs["authority"]["frameRate"]))
        rebind(inputs)
        with patch("guided_opening_graphic_proof.create_snapshot") as seal, \
                patch("graphics.graphics_render.render_entry_at_rate") as render:
            with self.assertRaisesRegex(ValueError, "hold|duration"):
                inspect_full_program_graphics(inputs, lambda: None)
        seal.assert_not_called()
        render.assert_not_called()

    def test_late_invalid_copy_and_native_canvas_mismatch_are_not_filtered_away(self) -> None:
        inputs = valid_inputs()
        inputs.documents["candidatePlan"]["graphicsTrack"][-1]["spec"] = {"unusedText": "TEST not read"}
        rebind(inputs)
        with self.assertRaisesRegex(ValueError, "template contract"):
            inspect_full_program_graphics(inputs, lambda: None)
        inputs = valid_inputs()
        inputs.documents["candidatePlan"]["target"]["width"] = 1280
        rebind(inputs)
        inputs.documents["frameBindings"]["targetHash"] = digest(inputs.documents["authority"]["target"])
        with self.assertRaisesRegex(RuntimeError, "full canvas"):
            inspect_full_program_graphics(inputs, lambda: None)

    def test_expired_caller_guard_and_mutated_packet_are_rejected(self) -> None:
        inputs = valid_inputs()
        def expired() -> None:
            raise RuntimeError("TEST original budget expired")
        with patch("guided_graphic_template.read_graphic_template") as reader:
            with self.assertRaisesRegex(RuntimeError, "expired"):
                inspect_full_program_graphics(inputs, expired)
            reader.assert_not_called()
        observations = 0
        def changed() -> None:
            nonlocal observations
            observations += 1
            if observations == 15:
                inputs.documents["candidatePlan"]["graphicsTrack"][-1]["spec"]["text"] = "TEST changed"
        with self.assertRaisesRegex(RuntimeError, "packet changed"):
            inspect_full_program_graphics(inputs, changed)

    def test_template_changes_during_preflight_reject_without_modifying_catalog(self) -> None:
        import guided_graphic_template as module
        inputs = valid_inputs(1)
        actual, reads = module.read_bytes, 0
        def changed(path: Path, maximum: int = 16 * 1024 * 1024) -> bytes:
            nonlocal reads
            reads += 1
            raw = actual(path, maximum)
            return raw if reads == 1 else raw + b"<!-- TEST concurrent change -->"
        with patch.object(module, "read_bytes", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "template changed"):
                inspect_full_program_graphics(inputs, lambda: None)

    def test_template_reader_rejects_contradictory_full_animation_span(self) -> None:
        inputs = valid_inputs(1)
        row = {**inputs.documents["frameBindings"]["graphics"][0],
            "entry": inputs.documents["candidatePlan"]["graphicsTrack"][0]}
        row["endFrameExclusive"] += 1
        with self.assertRaisesRegex(RuntimeError, "animation duration"):
            read_graphic_template(row, inputs.documents["authority"]["frameRate"])

    def test_budget_expiring_inside_final_input_hash_cannot_return_success(self) -> None:
        inputs = valid_inputs(1)
        expired = False
        def guard() -> None:
            if expired:
                raise RuntimeError("TEST deadline expired inside final hash")
        def checked(value: object) -> str:
            nonlocal expired
            result = digest(value)
            if value is inputs.documents:
                expired = checked.observations > 0
                checked.observations += 1
            return result
        checked.observations = 0
        with patch("guided_graphic_template.digest", side_effect=checked):
            with self.assertRaisesRegex(RuntimeError, "inside final hash"):
                inspect_full_program_graphics(inputs, guard)


if __name__ == "__main__":
    unittest.main(verbosity=2)
