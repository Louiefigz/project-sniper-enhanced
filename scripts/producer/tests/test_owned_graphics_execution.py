"""Owned internal hooks preserve the ordinary pipeline; no catalog/approval claims."""
from __future__ import annotations

import contextlib
import copy
import io
import shutil
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from assemble import AssembleJob, _composite, assemble
from graphics import graphics_stage as stage
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import (
    GraphicsComposition, OwnedGraphicsExecution, compose_owned, render_owned,
)
from guided_opening_picture import observe_picture
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import PrefixOracleRuntime, canonical_hash
from test_opening_prefix_contract import held
from test_opening_prefix_oracle import _fixture


def _proof(value: GraphicsComposition) -> dict:
    """Explicit TEST stub, never a media or actual prefix observation."""
    return {"kind": "verified-prefix-private-picture-composition", "outputPath": value.video_out,
        "output": {"path": value.video_out}, "deliveryApproved": False, "TEST_ONLY": True,
        "prefixOracle": {"kind": "compositor-prefix-oracle", "status": "verified",
            "inputs": [{"path": value.video_in}], "fullGraphHash": canonical_hash(list(value.clips)),
            "clock": {"frame_rate": value.frame_clock[0], "total_frames": value.frame_clock[1],
                      "width": value.canvas[0], "height": value.canvas[1]}}}


class OwnedGraphicsExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        """Construct isolated TEST callbacks, never a production execution claim."""
        self.guard, self.render = Mock(), Mock()
        self.owned = OwnedGraphicsExecution(self.render, _proof, self.guard)
        self.entry = {"kind": "TEST", "outStart": 0, "outEnd": 1, "spec": {"label": "TEST"}}
        self.value = GraphicsComposition("/TEST/base", "/TEST/out", ({"path": "/TEST/asset"},),
            CompositeOptions(eof_pass=True, ydif_file="/TEST/unused", frame_rate="24", video_only=True), (64, 36), ("24", 24))

    def test_only_exact_held_assembly_can_accept_hooks(self) -> None:
        """Reject unheld jobs before either assembly lane can execute."""
        job = AssembleJob("/TEST/base", {}, "/TEST/out", None, owned_graphics=self.owned)
        for changed in (job, replace(job, audio_clock_policy="source-float-v2"),
                        replace(job, held_program_selection=("/TEST/event", "a" * 64), graphic_frame_clock=("24", 24))):
            with patch("audio.assemble_source_audio.assemble_source_audio") as call, \
                    self.assertRaisesRegex(RuntimeError, "exact held"):
                assemble(changed)
            call.assert_not_called()
        with patch("audio.assemble_source_audio.assemble_source_audio") as call:
            valid = replace(job, audio_clock_policy="source-float-v2", held_program_selection=("/TEST/event", "a" * 64),
                            graphic_frame_clock=("24", 24))
            assemble(valid)
            call.assert_called_once_with(valid)

    def test_renderer_preserves_exact_original_candidate_order_and_entry(self) -> None:
        """Keep callback data isolated while retaining original composition order."""
        self.render.return_value = {"path": "/TEST/asset", "kind": "TEST", "key": "TEST", "fmt": "mp4", "cached": False}
        before = copy.deepcopy(self.entry)
        result = render_owned(self.owned, self.entry, 12)
        self.assertEqual(result, self.render.return_value)
        self.assertEqual(self.render.call_args.args, (before, 12))
        self.assertIsNot(self.render.call_args.args[0], self.entry)
        self.assertEqual(self.entry, before)
        self.assertEqual(self.guard.call_count, 2)

    def test_renderer_cannot_mutate_supplied_or_original_candidate(self) -> None:
        """Detect changes to either side of the callback boundary."""
        for target in ("supplied", "original"):
            def mutate(entry: dict, _order: int) -> dict:
                """Inject a TEST-only attempted change to candidate intent."""
                (entry if target == "supplied" else self.entry)["outEnd"] += 1
                return {}
            with self.subTest(target=target), self.assertRaisesRegex(RuntimeError, "changed its exact"):
                render_owned(replace(self.owned, render=mutate), self.entry, 0)

    def test_compositor_gets_actual_geometry_clock_but_no_missing_inline_tap(self) -> None:
        """Pass exact graph geometry and use the separate smoothness observer."""
        compose = Mock(side_effect=_proof)
        result = compose_owned(replace(self.owned, compose=compose), self.value)
        supplied = compose.call_args.args[0]
        self.assertEqual((supplied.canvas, supplied.frame_clock), ((64, 36), ("24", 24)))
        self.assertEqual(supplied.clips, self.value.clips)
        self.assertIsNot(supplied.clips[0], self.value.clips[0])
        self.assertIsNone(supplied.options.ydif_file)
        self.assertEqual(self.value.options.ydif_file, "/TEST/unused")
        self.assertFalse(result["deliveryApproved"])

    def test_compositor_graph_mutation_or_wrong_output_identity_fails(self) -> None:
        """Reject a changed graph or a result naming a different output."""
        def mutate(value: GraphicsComposition) -> dict:
            """Attempt to change a resolved placement within the TEST callback."""
            value.clips[0]["x"] = 12
            return _proof(value)
        with self.assertRaisesRegex(RuntimeError, "changed the actual"):
            compose_owned(replace(self.owned, compose=mutate), self.value)
        with self.assertRaisesRegex(RuntimeError, "omitted its exact"):
            compose_owned(replace(self.owned, compose=lambda value: _proof(replace(value, video_out="/TEST/other"))), self.value)

    def test_compositor_proof_must_bind_actual_full_graph_base_and_exact_clock(self) -> None:
        """A valid-looking proof for another call must not qualify this graph."""
        for change in ({"fullGraphHash": "a" * 64}, {"inputs": [{"path": "/TEST/other"}]},
                       {"clock": {"frame_rate": "25", "total_frames": 24, "width": 64, "height": 36}},
                       {"clock": {"frame_rate": "24", "total_frames": 25, "width": 64, "height": 36}},
                       {"clock": {"frame_rate": "24", "total_frames": 24, "width": 128, "height": 72}}):
            proof = _proof(self.value)
            proof["prefixOracle"].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, "actual full graph"):
                compose_owned(replace(self.owned, compose=lambda _: proof), self.value)

    def test_missing_clock_rejects_before_owned_or_ordinary_render(self) -> None:
        """Require the original exact frame clock before expensive execution."""
        job = stage.GraphicsJob("/TEST/base", "/TEST/out", [self.entry], owned_graphics=self.owned)
        with patch.object(stage, "render_entry") as unowned:
            with self.assertRaisesRegex(RuntimeError, "exact-frame"):
                stage.run_graphics_stage(job)
            self.render.assert_not_called()
            unowned.assert_not_called()

    def test_failed_owned_renderer_does_not_fall_back(self) -> None:
        """A failed owned callback cannot silently invoke the ordinary renderer."""
        self.render.side_effect = RuntimeError("TEST owned render failed")
        job = stage.GraphicsJob("/TEST/base", "/TEST/out", [self.entry], owned_graphics=self.owned)
        with patch.object(stage, "_clip_dims", return_value=(64, 36)), patch.object(stage, "_clip_fps", return_value=24), \
                patch.object(stage, "render_entry") as unowned:
            with self.assertRaisesRegex(RuntimeError, "TEST owned"):
                stage._render_all(job)
            unowned.assert_not_called()

    def test_owned_assembly_uses_standalone_smoothness_and_still_blocks_judder(self) -> None:
        """Removing the inline tap does not remove the judder failure gate."""
        job = AssembleJob("/TEST/base", {"graphicsTrack": []}, "/TEST/out", None,
            owned_graphics=self.owned, held_program_selection=("/TEST/event", "a" * 64))
        with patch.object(stage, "run_graphics_stage", return_value={"passes": 1}) as graphics, \
                patch("assemble._probe_fps", return_value=24), patch("assemble._read_inline_ydif") as inline, \
                patch("assemble._ydif_dup_ratio", return_value=1) as decoded, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "judders"):
                _composite(job)
            self.assertIs(graphics.call_args.args[0].owned_graphics, self.owned)
            inline.assert_not_called()
            decoded.assert_called_once()

    def test_publication_guard_checks_live_owner_before_and_after_existing_full_checks(self) -> None:
        """An expired owner blocks publication on either side of full validation."""
        from audio import assemble_source_audio as source
        candidate = SimpleNamespace(job=SimpleNamespace(plan_path="/TEST/plan", plan={}, owned_graphics=self.owned),
            directory=Path("/TEST/candidate"), plan_sha256="TEST-plan", preparation=None)
        qualified = SimpleNamespace(report=SimpleNamespace(final_sha256="TEST-final"), support={})
        for fail_at in ("before", "after"):
            self.guard.side_effect = [RuntimeError("TEST owner expired")] if fail_at == "before" \
                else [None, RuntimeError("TEST owner expired")]
            with patch.object(source, "file_hash", side_effect=["TEST-plan", "TEST-final"]) as hashes, \
                    patch.object(source, "verify_program_master") as master, \
                    patch.object(source, "_support_hashes", return_value={}), \
                    self.subTest(fail_at=fail_at), self.assertRaisesRegex(RuntimeError, "TEST owner expired"):
                source._candidate_current(candidate, object(), qualified)
            self.assertEqual(hashes.call_count, 0 if fail_at == "before" else 2)
            self.assertEqual(master.call_count, 0 if fail_at == "before" else 1)

    def test_private_staging_preserves_same_live_hook_without_recreating_its_clock(self) -> None:
        """Private staging must preserve, not renew, the existing execution owner."""
        from audio.assemble_source_audio import _staged_job
        job = AssembleJob("/TEST/base", {}, "/TEST/out", None, owned_graphics=self.owned)
        staged = _staged_job(SimpleNamespace(job=job, directory=Path("/TEST/private"), preparation=None))
        self.assertIs(staged.owned_graphics, self.owned)
        self.assertEqual(staged.out, "/TEST/private/final.mp4")
        self.assertEqual(job.out, "/TEST/out")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class OwnedGraphicsActualCompositionTests(unittest.TestCase):
    def test_real_valid_opening_proof_for_omitted_future_graphic_is_rejected(self) -> None:
        """Exercise actual encoding of a wrong full graph with matching intro pixels."""
        root = Path(tempfile.mkdtemp(prefix="sniper-owned-graph-binding-", dir="/private/tmp"))
        request = _fixture(root, "24000/1001")
        runtime = PrefixOracleRuntime(held(Path(shutil.which("ffmpeg"))), held(Path(shutil.which("ffprobe"))), str(root), 30)
        output = root / "candidate"
        output.mkdir(mode=0o700)
        value = GraphicsComposition(request.base.path, str(output / "picture.mp4"), request.full_clips,
            CompositeOptions(eof_pass=True, frame_rate="24000/1001", video_only=True), (64, 36), ("24000/1001", 24))
        changed = replace(request, full_clips=request.opening_clips, assets=request.assets[:2])
        observed = []

        def wrong_graph(actual: GraphicsComposition) -> dict:
            """Generate a real TEST counterexample omitting the future graphic."""
            end = time.monotonic() + 30
            proof = compose_verified_prefix(PrefixCompositionJob(changed, runtime, actual.video_out, lambda: end - time.monotonic()))
            observed.append(proof)
            return proof

        owned = OwnedGraphicsExecution(Mock(), wrong_graph, Mock())
        with self.assertRaisesRegex(RuntimeError, "actual full graph"):
            compose_owned(owned, value)
        self.assertTrue(observed[0]["prefixOracle"]["comparison"]["core"]["exactPreencodePixels"])
        self.assertFalse(observed[0]["deliveryApproved"])
        self.assertNotEqual(observed[0]["prefixOracle"]["fullGraphHash"], canonical_hash(list(value.clips)))
        print(f"TEST-only real different full graph refused: {root}")

    def test_actual_stage_places_and_encodes_the_graph_verified_by_prefix_oracle(self) -> None:
        """Observe actual placement, prefix comparison and complete picture decode."""
        root = Path(tempfile.mkdtemp(prefix="sniper-owned-graphics-", dir="/private/tmp"))
        request = _fixture(root, "24000/1001")
        runtime = PrefixOracleRuntime(held(Path(shutil.which("ffmpeg"))), held(Path(shutil.which("ffprobe"))), str(root), 30)
        output = root / "candidate"
        output.mkdir(mode=0o700)
        entries = [{"kind": "TEST-only-prepared-marker", "anchor": "own-screen", "outStart": row["outStart"],
                    "outEnd": row["outEnd"]} for row in request.full_clips]
        called, guarded = [], Mock()

        def render(entry: dict, order: int) -> dict:
            """Return an explicit TEST-prepared asset in the requested order."""
            self.assertEqual(entry, entries[order])
            called.append(order)
            return {"path": request.full_clips[order]["path"], "kind": entry["kind"], "key": str(order), "fmt": "mov", "cached": False}

        def compose(value: GraphicsComposition) -> dict:
            """Execute the oracle and encode for the actual resolved TEST graph."""
            self.assertEqual(value.frame_clock, ("24000/1001", 24))
            self.assertEqual(value.canvas, (64, 36))
            bound = replace(request, full_clips=value.clips)
            end = time.monotonic() + 30
            return compose_verified_prefix(PrefixCompositionJob(bound, runtime, value.video_out, lambda: end - time.monotonic()))

        owned = OwnedGraphicsExecution(render, compose, guarded)
        job = stage.GraphicsJob(request.base.path, str(output / "picture.mp4"), entries,
            eof_pass=True, graphic_frame_clock=("24000/1001", 24), owned_graphics=owned,
            placements_out=str(output / "graphics_placements.json"))
        with patch.object(stage, "render_entry") as unowned, patch.object(stage, "run_verify") as verify, \
                contextlib.redirect_stdout(io.StringIO()):
            result = stage.run_graphics_stage(job)
        self.assertEqual(called, [0, 1, 2])
        unowned.assert_not_called()
        verify.assert_called_once()
        self.assertTrue((output / "graphics_placements.json").is_file())
        self.assertEqual(result["frames_in"], result["frames_out"])
        self.assertTrue(result["ownedCompositionEvidence"]["prefixOracle"]["comparison"]["core"]["exactPreencodePixels"])
        tools = {"ffmpeg": {"path": runtime.ffmpeg.path}, "ffprobe": {"path": runtime.ffprobe.path}}
        observation = observe_picture(Path(job.video_out), ("24000/1001", 24, (64, 36)), tools)
        self.assertTrue(observation["videoDecodeSucceeded"])
        self.assertGreaterEqual(guarded.call_count, 10)
        print(f"TEST-only actual owned graphics stage evidence: {root}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
