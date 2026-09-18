"""Pure TEST packet/proof seams, not execution, rendered pixels or approval."""
from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import digest, file_hash
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import GraphicsComposition
from guided_body_prefix import BodyPrefixBinding, body_prefix_request
from guided_opening_frames import full_program_frames
from test_guided_body_frames import fixture


def _fixture() -> tuple:
    """Invented media refs are exercised only with the artifact reader mocked."""
    inputs = fixture(12)
    inputs.value.update(executionId="TEST original ID", executionInputHash="d" * 64, documents={"TEST": "untrusted fixture"})
    rows = full_program_frames(inputs)
    proofs, clips = [], []
    for row in rows:
        asset = {"path": f"/TEST/body/graphic-{row['order']}.mp4", "sha256": "a" * 64,
            "sizeBytes": 4, "width": 1920, "height": 1080}
        proofs.append({"actualAsset": asset, "candidateOrder": row["order"],
            "graphicId": row["graphicId"], "workerCleanupObserved": True})
        clips.append({"path": asset["path"], "outStart": row["entry"]["outStart"],
            "outEnd": row["entry"]["outEnd"], "anchor": "own-screen", "x": 0, "y": 0,
            "startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"],
            "placedBBox": [0, 0, 1920, 1080]})
    old = copy.deepcopy(proofs[:1])
    old[0]["actualAsset"]["path"] = "/TEST/opening/graphic-0.mp4"
    source = Path(__file__).resolve().parents[1] / "guided_opening_graphics.py"
    record = {"pipeline": {"executionClosure": [{"path": "scripts/producer/guided_opening_graphics.py",
        "sha256": file_hash(source)}]}, "receiptHash": "c" * 64,
        "pictures": {"policy": "global-composition-then-half-open-frame-trim-v1",
            "orderPolicy": "ordinary-outStart-ascending-stable-candidate-ties",
            "placementScope": "declared-own-screen-full-canvas-not-free-space-or-perceptual-proof",
            "candidateOrder": ["test-0"], "executedOrder": ["test-0"]}, "graphics": old,
        "fullProgram": {"base": {"path": "/TEST/opening/full-program-base/final.mp4",
            "sha256": "b" * 64, "sizeBytes": 8}}}
    authority = inputs.documents["authority"]
    record.update(inputPath=str(inputs.path), inputSha256=inputs.sha256,
        executionId=inputs.value["executionId"], executionInputHash=inputs.value["executionInputHash"],
        documents=copy.deepcopy(inputs.value["documents"]), authority=copy.deepcopy(authority))
    options = CompositeOptions(eof_pass=True, frame_rate=authority["frameRate"], video_only=True)
    value = GraphicsComposition(record["fullProgram"]["base"]["path"], "/TEST/body/picture.mp4",
        tuple(clips), options, (1920, 1080), (authority["frameRate"], authority["totalFrames"]))
    return value, BodyPrefixBinding(inputs, record, Path("/TEST/opening")), proofs


class GuidedBodyPrefixTests(unittest.TestCase):
    """No deleted late graphic, changed asset or hidden placement can enter the oracle."""

    def test_twelve_actual_rows_and_original_asset_are_retained_without_mutation(self) -> None:
        value, binding, proofs = _fixture()
        before = digest([binding.original_result, binding.inputs.documents, proofs])
        with patch("guided_body_prefix.read_graphics") as reader:
            request, evidence = body_prefix_request(value, binding, proofs)
        reader.assert_called_once()
        self.assertEqual(len(request.full_clips), 12)
        self.assertEqual(len(request.opening_clips), 1)
        self.assertEqual(len(request.assets), 13)
        self.assertEqual(request.full_clips, value.clips)
        self.assertEqual(request.opening_clips[0]["path"], "/TEST/opening/graphic-0.mp4")
        self.assertEqual(evidence["policy"], "pinned-opening-own-screen-origin-v1")
        self.assertIn("not-literal-captured", evidence["scope"])
        self.assertEqual(before, digest([binding.original_result, binding.inputs.documents, proofs]))

    def test_missing_or_stale_derivation_source_blocks_before_artifact_read(self) -> None:
        for closure in ([], [{"path": "scripts/producer/guided_opening_graphics.py", "sha256": "0" * 64}]):
            value, binding, proofs = _fixture()
            binding.original_result["pipeline"]["executionClosure"] = closure
            with patch("guided_body_prefix.read_graphics") as reader:
                with self.assertRaisesRegex(RuntimeError, "derivation source"):
                    body_prefix_request(value, binding, proofs)
            reader.assert_not_called()

    def test_reader_rejection_is_not_swallowed_by_graph_projection(self) -> None:
        with patch("guided_body_prefix.read_graphics", side_effect=RuntimeError("TEST held bytes changed")):
            with self.assertRaisesRegex(RuntimeError, "held bytes changed"):
                body_prefix_request(*_fixture())

    def test_self_consistent_new_input_ranges_cannot_change_the_original_held_opening(self) -> None:
        value, binding, proofs = _fixture()
        binding.inputs.documents["authority"]["review"]["endFrameExclusive"] = 90
        with patch("guided_body_prefix.read_graphics") as reader:
            with self.assertRaisesRegex(RuntimeError, "result/input/range authority"):
                body_prefix_request(value, binding, proofs)
        reader.assert_not_called()

    def test_missing_late_graphic_and_changed_order_or_asset_block(self) -> None:
        value, binding, proofs = _fixture()
        candidates = [replace(value, clips=value.clips[:-1]), replace(value, clips=value.clips[::-1])]
        changed = copy.deepcopy(value.clips)
        changed[-1]["path"] = "/TEST/foreign.mp4"
        candidates.append(replace(value, clips=changed))
        for candidate in candidates:
            with self.subTest(clips=candidate.clips[-1]):
                with self.assertRaisesRegex(RuntimeError, "omitted|ordered held"):
                    body_prefix_request(candidate, binding, proofs)

    def test_hidden_geometry_and_frame_mutations_are_not_removed(self) -> None:
        for change in ({"x": 1}, {"pipHole": {}}, {"scaleDims": [1920, 1080]},
                       {"startFrame": 2}, {"placedBBox": [0, 0, 1920, 1079]}):
            value, binding, proofs = _fixture()
            value.clips[0].update(change)
            with self.subTest(change=change):
                with self.assertRaisesRegex(RuntimeError, "closed contract|ordered held"):
                    body_prefix_request(value, binding, proofs)

    def test_full_clock_base_and_actual_canvas_must_match_original(self) -> None:
        value, binding, proofs = _fixture()
        changes = [replace(value, video_in="/TEST/foreign.mp4"), replace(value, canvas=(1280, 720)),
            replace(value, frame_clock=("30", value.frame_clock[1]))]
        for changed in changes:
            with self.assertRaisesRegex(RuntimeError, "base/canvas/frame clock"):
                body_prefix_request(changed, binding, proofs)

    def test_option_audio_trim_eof_and_unowned_runner_changes_are_rejected(self) -> None:
        value, binding, proofs = _fixture()
        for changes in ({"video_only": False}, {"frame_range": (0, 100)}, {"eof_pass": False},
                        {"command_runner": lambda _: None}, {"ffmpeg": "/TEST/other"}):
            changed = replace(value, options=replace(value.options, **changes))
            with self.assertRaisesRegex(RuntimeError, "options"):
                body_prefix_request(changed, binding, proofs)

    def test_original_unknown_policy_and_missing_cleanup_do_not_become_pixels_proof(self) -> None:
        value, binding, proofs = _fixture()
        binding.original_result["pictures"]["policy"] = "TEST other graph"
        with self.assertRaisesRegex(RuntimeError, "policy"):
            body_prefix_request(value, binding, proofs)
        value, binding, proofs = _fixture()
        proofs[-1]["workerCleanupObserved"] = False
        with self.assertRaisesRegex(RuntimeError, "ordered held"):
            body_prefix_request(value, binding, proofs)


if __name__ == "__main__":
    unittest.main()
