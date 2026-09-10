"""Captioned body cold-route wiring with actual tiny pins and TEST picture records."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _presenter_caption_body_read_fixture import CaptionBodyReadFixture
from cut_preview_io import digest
from guided_body_execution import assert_body_files, hold_body_file
from guided_body_read_proof import _prefix
from guided_opening_result import held_ref


class PresenterCaptionBodyReadRouteTests(unittest.TestCase):
    """Only prior graphic/approval derivation is stubbed, never actual new cold checks."""

    def setUp(self) -> None:
        """Retain original source/caption/tool identities and synthetic retained output."""
        self.fixture = CaptionBodyReadFixture()
        self.addCleanup(self.fixture.close)
        item = self.fixture
        root, original = item.original.fixture.root, item.original
        base = original.base
        opening = {"pictures": original.pictures,
            "fullProgram": {"base": {"path": base.path, "sha256": base.sha256, "sizeBytes": base.size_bytes}}}
        control = SimpleNamespace(root=root, documents={"openingResult": opening,
            "heldInput": {"opening": {"outputRoot": str(root)}}})
        tools = {name: {"path": row.path, "sha256": row.sha256}
                 for name, row in zip(("ffmpeg", "ffprobe"), item.context.tools)}
        files = tuple(hold_body_file(Path(row.path), row.sha256) for row in item.context.tools)
        self.work = SimpleNamespace(inputs=original.inputs, control=control, captions=original.held,
            pipeline={"opening": {"tools": tools}}, files=files, clock=original.fixture.probe.deadline,
            guard=self.guard)
        self.record = {"graphics": [], "resolvedClips": [], "composition": item.composition}
        self.plain = replace(item.request, assets=(), full_clips=(), opening_clips=(), caption_tail=None)
        self.derivation = item.composition["originalGraphDerivation"]
        item.composition["originalGraphDerivation"] = {**self.derivation,
            "captionProjectionHash": original.held.data_hash,
            "combinedOpeningGraphHash": digest(list(item.request.opening_clips))}

    def guard(self) -> None:
        """The exact original tiny source/tool and caller clock stay live."""
        self.fixture.original.fixture.guard()
        assert_body_files(self.work.files, self.work.clock)

    def read(self) -> None:
        """Real caption-tail projection/cold read; prior graphic/approval derivation is a stub."""
        with self.fixture.selected(), \
                patch("guided_body_read_proof.body_prefix_metadata", return_value=(self.plain, self.derivation)), \
                patch("guided_presenter_capture.capture_selection", return_value=self.fixture.original.selection), \
                patch("guided_presenter_observation.run_text", side_effect=AssertionError("no selected decode")):
            _prefix(self.record, self.work)

    def test_captioned_branch_rederives_pages_and_strongly_reads_retained_picture(self) -> None:
        """Graph/report checks do not replace the actual caller's retained artifact read."""
        with patch("guided_body_read_proof.held_ref", wraps=held_ref) as picture:
            self.read()
        picture.assert_called_once()
        self.assertEqual(picture.call_args.args[2], self.work.control.root / "picture-only.mp4")

    def test_lost_held_caption_projection_is_not_an_uncaptioned_body_fallback(self) -> None:
        """The exact original new profile cannot proceed on stored proof flags alone."""
        self.work.captions = None
        with self.assertRaisesRegex(RuntimeError, "original opening derivation"):
            self.read()


if __name__ == "__main__":
    unittest.main()
