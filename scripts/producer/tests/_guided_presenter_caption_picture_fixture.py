"""Held TEST caption files and live control flow; encoder/probe leaves are stubs."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import stat
from unittest.mock import patch

from _presenter_caption_clearance_fixture import ClearanceFixture
from guided_opening_picture import compose_ranges
from guided_opening_presenter import OpeningPictureContext, OpeningPresenterContext
from test_opening_prefix_contract import held


class CaptionPictureFixture(ClearanceFixture):
    """Original rational clock and caption bytes, not actual rendered picture proof."""

    def __init__(self) -> None:
        """Hold the base independently and preserve the caption plan's original bytes."""
        super().__init__("30000/1001")
        self.authority = self.inputs.documents["authority"]
        self.authority["core"] = {"startFrame": 0, "endFrameExclusive": 60}
        self.base = self.root / "TEST-base-not-media.mp4"
        self.base.write_bytes(b"TEST independently held base; no decoded picture claim")
        self.presenter = OpeningPresenterContext(self.owner, self.inputs.documents["candidatePlan"],
                                                 held(self.base), self.inputs)
        self.tools = {"ffprobe": {"path": self.runtime.ffprobe.path}, "ffmpeg": {"path": self.runtime.ffprobe.path}}
        self.picture_context = OpeningPictureContext(self.root, self.authority, self.tools, self.presenter)
        self.commands = []
        self.events = []

    def compose(self, _base: str, clips: list, output: str, options: object) -> int:
        """Retain actual call arguments while invoking no encoder or child process."""
        self.events.append("compose")
        self.commands.append((deepcopy(clips), output, deepcopy(options)))
        return 1

    def observed_picture(self, path: Path, expected: tuple, _tools: dict) -> dict:
        """Explicit mechanical-output stub, not decoded picture or approval evidence."""
        self.events.append("observe-picture")
        rate, frames, canvas = expected
        return {"path": str(path), "sha256": "f" * 64, "frames": frames,
                "frameRate": rate, "width": canvas[0], "height": canvas[1]}

    def render(self, context: object = None) -> dict:
        """Exercise real live range and clearance control flow over stub final pictures."""
        with patch("guided_opening_picture.composite", side_effect=self.compose), \
                patch("guided_opening_picture.observe_picture", side_effect=self.observed_picture):
            return compose_ranges(self.base, [], context or self.picture_context, self.held)

    def absent_captions(self) -> dict:
        """Exercise the real pre-encode missing-owner rejection without native work."""
        with patch("guided_opening_picture.composite", side_effect=self.compose), \
                patch("guided_opening_picture.observe_picture", side_effect=self.observed_picture):
            return compose_ranges(self.base, [], self.picture_context)

    def corrupt_owned_caption(self, target: Path) -> None:
        """Fault only a captured file below this exact resolved TEST fixture root."""
        root = self.root.resolve(strict=True)
        if target != target.resolve(strict=True) or not target.is_relative_to(root) \
                or str(target) not in {row.path for row in self.held.files}:
            raise RuntimeError("TEST mutation target is not an owned held caption file")
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("TEST mutation target is not an owned single-link regular file")
        target.write_bytes(b"TEST late changed caption metadata")
