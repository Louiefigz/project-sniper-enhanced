"""Real cold-read pins with TEST body metadata/output, not authenticated rendered media."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_presenter_body_read_fixture import PresenterBodyReadFixture
from guided_body_execution import assert_body_files, hold_body_file
from guided_body_read_proof import _prefix
from test_opening_prefix_contract import held


class PresenterBodyReadRouteTests(unittest.TestCase):
    """Exercise branch wiring; original graphic/approval authority is an explicit stub."""

    def setUp(self) -> None:
        """Hold actual tiny inputs/tools/output bytes without launching media work."""
        self.fixture = PresenterBodyReadFixture()
        self.addCleanup(self.fixture.close)
        item = self.fixture
        root = item.original.probe.root
        retained = root / "picture-only.mp4"
        retained.write_bytes(b"TEST retained bytes, not a decoded video")
        result = held(retained)
        composition = deepcopy(item.composition)
        composition["outputPath"] = str(root / "body-candidate/final.mp4")
        composition["output"] = {**asdict(result), "path": composition["outputPath"]}
        composition["retainedPicture"] = {"path": result.path, "sha256": result.sha256, "sizeBytes": result.size_bytes}
        composition["originalGraphDerivation"] = {"TEST": "graphic/approval projection is stubbed"}
        self.derivation = composition["originalGraphDerivation"]
        self.record = {"graphics": [], "resolvedClips": [], "composition": composition}
        base = item.request.base
        original = {"pictures": item.context.opening_pictures,
                    "fullProgram": {"base": {"path": base.path, "sha256": base.sha256, "sizeBytes": base.size_bytes}}}
        control = SimpleNamespace(root=root, documents={"openingResult": original,
                                  "heldInput": {"opening": {"outputRoot": str(root)}}})
        tools = {name: {"path": row.path, "sha256": row.sha256}
                 for name, row in zip(("ffmpeg", "ffprobe"), item.context.tools)}
        files = tuple(hold_body_file(Path(row.path), row.sha256) for row in item.context.tools)
        self.work = SimpleNamespace(inputs=item.original.inputs, control=control, captions=None,
            pipeline={"opening": {"tools": tools}}, files=files, clock=item.original.probe.deadline,
            guard=self.guard)

    def guard(self) -> None:
        """Actual original source and initial dependency identity checks stay live."""
        self.fixture.original.guard()
        assert_body_files(self.work.files, self.work.clock)

    def read(self) -> None:
        """Stub only prior graphic/approval projection, not new cold read or file lifetimes."""
        with patch("guided_body_read_proof.body_prefix_metadata", return_value=(self.fixture.request, self.derivation)), \
                patch("guided_body_read_proof._composition_evidence", side_effect=AssertionError("no legacy graph")), \
                patch("guided_presenter_observation.run_text", side_effect=AssertionError("no decode")):
            _prefix(self.record, self.work)

    def test_selected_profile_uses_cold_schema2_reader_and_actual_held_files(self) -> None:
        """No live presenter is reconstructed and no selected asset is decoded twice."""
        self.read()

    def test_missing_initial_tool_hold_cannot_adopt_a_later_stat(self) -> None:
        """Even correct tool path/SHA metadata is insufficient without its first hold."""
        self.work.files = self.work.files[1:]
        with patch("guided_presenter_capture.pin_executable") as pin, \
                self.assertRaisesRegex(RuntimeError, "original held dependency"):
            self.read()
        pin.assert_not_called()

    def test_changed_retained_picture_bytes_are_not_covered_by_prefix_graph_hash(self) -> None:
        """The strong artifact read remains mandatory after relational proof checks."""
        Path(self.record["composition"]["retainedPicture"]["path"]).write_bytes(b"TEST mutation")
        with self.assertRaises(RuntimeError):
            self.read()

    def test_different_original_derivation_is_not_replaced_by_current_metadata(self) -> None:
        """The actual opening derivation remains independently required by the caller."""
        self.record["composition"]["originalGraphDerivation"] = {"TEST": "changed"}
        with self.assertRaisesRegex(RuntimeError, "original opening derivation"):
            self.read()


if __name__ == "__main__":
    unittest.main()
