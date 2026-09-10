"""TEST-only live hook/evidence faults; no real render or admission in this suite."""
from __future__ import annotations

import copy
import subprocess
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, patch

from _guided_presenter_observation_fixture import ObservationFixture
from assemble import AssembleJob, assemble
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution, compose_owned
from guided_caption_execution import OwnedCaptionExecution
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_observation import observe_presenter_asset
from opening_prefix_contract import HeldPrefixInput, PrefixClock, canonical_hash
from opening_prefix_graphs import PresenterGraphLane, presenter_graph_record


def _proof(value: GraphicsComposition) -> dict:
    """Explicit TEST stub proof to exercise binding checks, never actual output."""
    base = HeldPrefixInput(value.video_in, "f" * 64, 1)
    assets, tool = value.presenter.held_assets(), value.presenter.runtime.ffprobe
    lane = PresenterGraphLane((*value.clips, *value.caption_clips), len(value.caption_clips) or None,
                              value.options.presenter, assets)
    clock = PrefixClock(*value.frame_clock, *value.canvas)
    graph = presenter_graph_record(clock, base, lane)
    inputs = [asdict(row) for row in (base, *assets, HeldPrefixInput(tool.path, tool.sha256, tool.size_bytes))]
    return {"schemaVersion": 2, "kind": "verified-presenter-prefix-private-picture-composition",
        "outputPath": value.video_out, "output": {"path": value.video_out}, "deliveryApproved": False,
        "TEST_ONLY": "stub observations/proof; no genuine admission, decode, render, quality or approval",
        "prefixOracle": {"schemaVersion": 2, "kind": "presenter-compositor-prefix-oracle",
            "status": "verified", "inputs": inputs, "clock": asdict(clock), "fullGraphHash": canonical_hash(graph),
            "layerPolicy": {"kind": "held-presenter-then-graphics-then-caption-pages-v1",
                "fullPresenterWindows": len(value.options.presenter.windows), "openingPresenterWindows": 1,
                "fullCaptionTail": len(value.caption_clips), "openingCaptionTail": len(value.caption_clips)}}}


class OwnedPresenterCompositionTests(unittest.TestCase):
    """Only the live owner injects graphs, and old proofs cannot cover new work."""

    def setUp(self) -> None:
        """Use TEST-only source metadata and leaf probe JSON, without any process."""
        self.fixture = ObservationFixture()
        self.addCleanup(self.fixture.close)
        responses = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.fixture.raw()]
        with patch("guided_presenter_observation.run_text", side_effect=responses):
            observed = observe_presenter_asset(self.fixture.selected, self.fixture.source,
                                               "30000/1001", self.fixture.runtime)
        self.presenter = OwnedPresenterExecution((self.fixture.selected,), (observed,),
                                                 "30000/1001", self.fixture.runtime)
        self.compose = Mock(side_effect=_proof)
        self.execution = OwnedGraphicsExecution(Mock(), self.compose, Mock(), presenter=self.presenter)
        self.value = GraphicsComposition("/TEST/base.mp4", "/TEST/output.mp4", (),
            CompositeOptions(eof_pass=True, frame_rate="30000/1001", video_only=True), (64, 36), ("30000/1001", 24))

    def test_live_owner_injects_picture_before_graphics_and_retains_original_value(self) -> None:
        """The ordinary caller supplies no serialized layout ownership."""
        result = compose_owned(self.execution, self.value)
        supplied = self.compose.call_args.args[0]
        self.assertIs(supplied.presenter, self.presenter)
        self.assertEqual(supplied.options.presenter, self.presenter.full_graph())
        self.assertIsNone(self.value.presenter)
        self.assertIsNone(self.value.options.presenter)
        self.assertEqual(result["schemaVersion"], 2)
        self.assertFalse(result["deliveryApproved"])

    def test_caller_supplied_graph_owner_or_serialized_owner_rejects_before_callback(self) -> None:
        """Neither low-level options nor JSON can substitute for the live hook."""
        values = (replace(self.value, presenter=self.presenter),
                  replace(self.value, options=replace(self.value.options, presenter=self.presenter.full_graph())))
        for value in values:
            with self.assertRaisesRegex(RuntimeError, "caller-supplied"):
                compose_owned(self.execution, value)
        with self.assertRaisesRegex(RuntimeError, "live internal"):
            compose_owned(replace(self.execution, presenter={"schemaVersion": 2}), self.value)
        self.compose.assert_not_called()

    def test_old_schema_or_clip_only_hash_cannot_cover_presenter_work(self) -> None:
        """Changing a label cannot relabel legacy proof bytes as combined output."""
        mutations = (
            lambda proof: proof.update(schemaVersion=1),
            lambda proof: proof.update(kind="verified-prefix-private-picture-composition"),
            lambda proof: proof["prefixOracle"].update(schemaVersion=1),
            lambda proof: proof["prefixOracle"].update(kind="compositor-prefix-oracle"),
            lambda proof: proof["prefixOracle"].update(fullGraphHash=canonical_hash([])),
        )
        for change in mutations:
            def compose(value: GraphicsComposition) -> dict:
                """Return a precise TEST proof fault, without touching actual input."""
                proof = _proof(value)
                change(proof)
                return proof
            with self.assertRaises(RuntimeError):
                compose_owned(replace(self.execution, compose=compose), self.value)

    def test_correct_hash_without_actual_asset_or_tool_inventory_is_inconsistent(self) -> None:
        """Graph identity and independently held byte inventory must agree."""
        for index in (1, 2):
            def compose(value: GraphicsComposition) -> dict:
                """Omit one held presenter dependency from the TEST receipt."""
                proof = _proof(value)
                proof["prefixOracle"]["inputs"].pop(index)
                return proof
            with self.assertRaisesRegex(RuntimeError, "asset/tool inventory"):
                compose_owned(replace(self.execution, compose=compose), self.value)

    def test_mutated_supplied_geometry_cannot_change_the_owner_or_gain_a_proof(self) -> None:
        """A valid different geometry is still not the graph originally supplied."""
        def compose(value: GraphicsComposition) -> dict:
            """Change one legal start frame before returning its self-consistent TEST proof."""
            object.__setattr__(value.options.presenter.windows[0].geometry.timing, "start_frame", 3)
            return _proof(value)
        with self.assertRaisesRegex(RuntimeError, "changed the actual resolved graph"):
            compose_owned(replace(self.execution, compose=compose), self.value)
        self.assertEqual(self.presenter.full_graph().windows[0].geometry.timing.start_frame, 2)

    def test_captions_remain_last_and_need_new_combined_policy(self) -> None:
        """Caption-only evidence cannot qualify the presenter beneath the same pages."""
        captions = OwnedCaptionExecution(None, Mock())  # TEST-only page owner; no held projection claim.
        clips = ({"path": "/TEST/page.mov", "compositionRole": "caption-page"},)
        execution = replace(self.execution, captions=captions)
        with patch.object(OwnedCaptionExecution, "clips", return_value=clips):
            proof = compose_owned(execution, self.value)
        self.assertEqual(proof["prefixOracle"]["layerPolicy"]["fullCaptionTail"], 1)
        self.assertEqual(self.compose.call_args.args[0].caption_clips, clips)
        changed = copy.deepcopy(proof)
        changed["prefixOracle"]["layerPolicy"]["kind"] = "graphics-then-held-caption-pages-v1"
        with patch.object(OwnedCaptionExecution, "clips", return_value=clips):
            with self.assertRaisesRegex(RuntimeError, "combined layer binding"):
                compose_owned(replace(execution, compose=lambda _: changed), self.value)

    def test_unowned_or_missing_track_is_refused_before_source_audio_or_graphics(self) -> None:
        """The ordinary assembler cannot silently ignore a present new lane field."""
        plan = {"presenterLayouts": []}
        jobs = (AssembleJob("/TEST/base", plan, "/TEST/out", None),
            AssembleJob("/TEST/base", plan, "/TEST/out", None, audio_clock_policy="source-float-v2",
                held_program_selection=("/TEST/event", "a" * 64), graphic_frame_clock=("30000/1001", 24),
                owned_graphics=replace(self.execution, presenter=None)),
            AssembleJob("/TEST/base", {}, "/TEST/out", None, audio_clock_policy="source-float-v2",
                held_program_selection=("/TEST/event", "a" * 64), graphic_frame_clock=("30000/1001", 24),
                owned_graphics=self.execution))
        with patch("audio.assemble_source_audio.assemble_source_audio") as renderer:
            for job in jobs:
                self.assert_assembly_refused(job)
        renderer.assert_not_called()

    def assert_assembly_refused(self, job: AssembleJob) -> None:
        """Keep each exact refusal assertion outside the outer dependency patch."""
        with self.assertRaises(RuntimeError):
            assemble(job)


if __name__ == "__main__":
    unittest.main()
