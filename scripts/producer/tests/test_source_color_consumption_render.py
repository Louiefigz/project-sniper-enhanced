"""Actual context/cut/master/private preparation dispatch with TEST native and proof leaves.

Only exact disposable TEST work directories are created. No source/dependency
fault writes, media encode, admission, decoder, cache receipt or approval runs.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_consumption_fixture import SourceColorConsumptionFixture
from _source_color_consumption_render_fixture import SourceColorRenderFixture
from audio import render_audio_master as audio
from cross_runtime_canonical_json import canonical_compact_json
from guided_opening_prepare import prepare_source_color_full_program
from guided_source_color_base_context import SourceColorBaseContext
import render


class SourceColorConsumptionRenderTests(unittest.TestCase):
    """Use actual original source holders while stubbing only process/output proof leaves."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture fresh current code once and hold exact inert source metadata for this cohort."""
        cls.fixture = SourceColorConsumptionFixture(current_batch_test_pins())
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.holder = cls.fixture.identity()

    def setUp(self) -> None:
        """Each attempted preparation receives one genuinely new private recorder."""
        self.context = self.fixture.base_context(self.holder)
        self.live = SourceColorRenderFixture(self.fixture, self.context)
        self.ctx = self.live.ctx

    def test_actual_cut_and_master_observations_complete_same_context(self) -> None:
        """No generic guard counter can replace these actual lower encoder/proof calls."""
        source, result = self.live.run()
        record = self.context.consumption_record()
        self.assertEqual(record["manifestation"]["concatPath"], source)
        self.assertEqual(record["master"]["inputPath"], source)
        self.assertEqual(record["pictureCopy"]["picturePackets"], 18)
        self.assertIs(self.context.consumption, self.context.consumption)
        self.assertEqual(record["basePublication"]["receipt"], self.live.sealed)
        self.assertEqual(record["basePublication"]["receipt"]["path"], result["out"])
        self.assertEqual(json.loads(canonical_compact_json(record)), record)

    def test_internal_preparation_requires_actual_hooks_then_refuses_replay(self) -> None:
        """The shared body is TEST-stubbed, but it actually invokes both production encode paths."""
        marker = object()

        def prepared(_inputs: object, _root: object, owners: tuple) -> object:
            """Model only the shared render entry, not a fabricated complete consumption DTO."""
            self.assertIs(owners[2], self.context)
            self.live.run()
            return marker

        with patch("guided_opening_prepare._prepare", side_effect=prepared) as body:
            self.assertIs(prepare_source_color_full_program(self.fixture.inputs, self.fixture.root, self.context), marker)
            self.assertRaisesRegex(RuntimeError, "cannot replay", prepare_source_color_full_program,
                                   self.fixture.inputs, self.fixture.root, self.context)
        body.assert_called_once()

    def test_substituted_recorder_refuses_before_any_stage(self) -> None:
        """Even another actual same-holder recorder is not this context's original identity."""
        original = self.context._consumption
        object.__setattr__(self.context, "_consumption", self.fixture.recorder(self.holder))
        self.assertRaisesRegex(RuntimeError, "original arguments", SourceColorBaseContext.assert_metadata, self.context)
        object.__setattr__(self.context, "_consumption", original)

    def test_late_copy_proof_change_refuses_receipt_and_poisoned_completion(self) -> None:
        """A payload hash callback cannot publish swapped packet evidence after the actual join."""
        with ExitStack() as stack:
            self.live.cut_leaves(stack)
            source = render.cut_stage(self.ctx)
            leaves = self.live.master_leaves(stack)
            delivered = []

            def mixed(output: str, encoder: object) -> dict:
                """Retain the actual TEST coordinator return for an in-memory fault only."""
                result = self.live.mix(output, encoder)
                delivered.append(result)
                return result

            stack.enter_context(patch.object(audio, "render_qualified_mix", side_effect=mixed))
            leaves["file_sha256"].side_effect = lambda *_: (delivered[0]["picture"].update(picturePackets=17), "e" * 64)[1]
            self.assertRaisesRegex(RuntimeError, "picture-copy proof|publication differs", render.master_stage, self.ctx, source, None)
        leaves["seal_audio_record"].assert_not_called()
        self.assertRaisesRegex(RuntimeError, "failed encode", self.context.consumption_record)

    def test_payload_substitution_by_publisher_cannot_be_rebaselined(self) -> None:
        """Even a consistent new hash cannot authorize changing the already-held final path."""
        with ExitStack() as stack:
            self.live.cut_leaves(stack)
            source = render.cut_stage(self.ctx)
            leaves = self.live.master_leaves(stack)

            def substituted(path: str, payload: dict) -> dict:
                """Mutate only the TEST in-memory publisher argument, never a file."""
                payload["path"] += ".TEST-other"
                return self.live.seal(path, payload)

            leaves["seal_audio_record"].side_effect = substituted
            self.assertRaisesRegex(RuntimeError, "publication changed", render.master_stage, self.ctx, source, None)
        self.assertRaisesRegex(RuntimeError, "failed encode", self.context.consumption_record)

    def test_finalizer_cannot_change_retained_sealed_receipt(self) -> None:
        """Hold the actual publisher return before invoking any later finalizer."""
        with ExitStack() as stack:
            self.live.cut_leaves(stack)
            source = render.cut_stage(self.ctx)
            leaves = self.live.master_leaves(stack)
            leaves["finalize_master"].side_effect = lambda *_: (
                self.live.sealed.update(sha256="0" * 64), {"out": self.ctx.out_dir + "/final.mp4"})[1]
            self.assertRaisesRegex(RuntimeError, "publication changed", render.master_stage, self.ctx, source, None)

    def test_last_original_callback_cannot_change_sealed_receipt(self) -> None:
        """The final owner callback does not turn an altered actual return into fresh authority."""
        self.fixture.guard.side_effect = lambda: self.live.sealed.update(approved=True) if self.live.sealed else None
        try:
            self.assertRaisesRegex(RuntimeError, "publication changed", self.live.run)
        finally:
            self.fixture.guard.side_effect = None

    def test_returned_master_result_remains_held_after_success(self) -> None:
        """The exact actual result remains original; changing it poisons subsequent context reads."""
        _source, result = self.live.run()
        result["source_audio_receipt_hash"] = "0" * 64
        self.assertRaisesRegex(RuntimeError, "publication changed", self.context.consumption_record)

    def test_lower_hooks_without_actual_publication_do_not_complete_context(self) -> None:
        """Successful native/proof hooks alone are not a sealed final base publication."""
        recorder = self.context.consumption
        self.fixture.cuts(recorder)
        picture = self.fixture.master(recorder)
        recorder.observe_master_picture(picture)
        from guided_source_color_consumption_records import copy_proof
        recorder.complete_master_copy(picture, copy_proof(picture))
        recorder.record()
        self.assertRaisesRegex(RuntimeError, "publication is incomplete", self.context.consumption_record)

    def test_source_only_channel_stage_uses_original_bus_not_intermediate_aac(self) -> None:
        """Actual typed source bus/admission is required before bypassing redundant AAC repair."""
        self.live.bus()
        source = str(self.fixture.root / "mezzanine.mp4")
        with patch.object(render, "dead_channel_prefix", return_value=("TEST repair", None)) as detect, \
                patch.object(render.subprocess, "run") as native:
            self.assertEqual(render.channels_stage(self.ctx, source), source)
        detect.assert_not_called()
        native.assert_not_called()
        self.assertEqual(self.ctx.bootstrap_trace[-1]["reason"], "source-float bus applies original source channel receipts")

    def test_source_only_channel_stage_refuses_missing_or_substituted_bus(self) -> None:
        """Neither absent audio authority nor equal reconstructed admission grants the handoff."""
        with patch.object(render, "dead_channel_prefix") as detect:
            self.assertRaisesRegex(RuntimeError, "actual original", render.channels_stage, self.ctx, "/TEST/concat")
            bus = self.live.bus()
            self.ctx.audio_admission = replace(bus.admission)
            self.assertRaisesRegex(RuntimeError, "actual original", render.channels_stage, self.ctx, "/TEST/concat")
        detect.assert_not_called()

    def test_source_only_channel_first_callback_cannot_replace_actual_bus(self) -> None:
        """The original bus is captured before the first source-context callback."""
        bus = self.live.bus()
        self.fixture.guard.side_effect = lambda: setattr(self.ctx, "source_audio_bus", replace(bus))
        try:
            self.assertRaisesRegex(RuntimeError, "channel bus changed", render.channels_stage, self.ctx, "/TEST/concat")
        finally:
            self.fixture.guard.side_effect = None


if __name__ == "__main__":
    unittest.main()
