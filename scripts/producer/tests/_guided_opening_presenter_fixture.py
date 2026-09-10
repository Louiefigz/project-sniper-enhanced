"""TEST-only live owner with probe facts stubbed; never media or source admission."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import subprocess
from unittest.mock import patch

from _guided_presenter_observation_fixture import ObservationFixture
from cut_preview_io import digest
from graphics.presenter_layout_contract import PresenterCanvas, declaration_payload
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_opening_presenter import OpeningPictureContext, OpeningPresenterContext
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_observation import observe_presenter_asset
from test_opening_prefix_contract import held


class OpeningPresenterFixture:
    """Original48-frame metadata with crossing and future windows and tiny held bytes."""

    def __init__(self) -> None:
        """Exercise actual control flow while labeling probe facts explicitly synthetic."""
        self.source = ObservationFixture()
        self.root = self.source.root
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.source.raw()]
        with patch("guided_presenter_observation.run_text", side_effect=results):
            observed = observe_presenter_asset(self.source.selected, self.source.source,
                "30000/1001", self.source.runtime)
        payload = declaration_payload(self.source.selected.geometry)
        canvas = PresenterCanvas(64, 36, 48, "yuv420p")
        selected = tuple(replace(self.source.selected, operation_index=index,
            geometry=compile_presenter_geometry(payload, canvas, span))
            for index, span in ((3, (2, 18)), (8, (30, 42))))
        self.owner = OwnedPresenterExecution(selected, (observed,), "30000/1001", self.source.runtime)
        self.plan = {"presenterLayouts": [{"operationIndex": row.operation_index,
            "startFrame": row.geometry.timing.start_frame, "endFrameExclusive": row.geometry.timing.end_frame_exclusive,
            "layout": declaration_payload(row.geometry)} for row in selected]}
        self.authority = {"frameRate": "30000/1001", "totalFrames": 48, "target": {"width": 64, "height": 36},
            "candidatePlanHash": digest(self.plan), "core": {"startFrame": 0, "endFrameExclusive": 6},
            "review": {"startFrame": 0, "endFrameExclusive": 12}}
        self.base = self.root / "TEST-base-not-media.mp4"
        self.base.write_bytes(b"TEST only independent base bytes, not a decoded picture")
        self.presenter = OpeningPresenterContext(self.owner, self.plan, held(self.base))
        self.tools = {"ffprobe": {"path": self.source.runtime.ffprobe.path},
                      "ffmpeg": {"path": self.source.runtime.ffprobe.path}}
        self.context = OpeningPictureContext(self.root, self.authority, self.tools, self.presenter)
        self.commands = []

    def compose(self, _base: str, clips: list, output: str, options: object) -> int:
        """Capture actual shared caller arguments without running any encoder."""
        self.commands.append((deepcopy(clips), output, deepcopy(options)))
        return 1

    def observed(self, path: Path, expected: tuple, _tools: dict) -> dict:
        """Explicit output stub, never actual decode/quality evidence."""
        rate, frames, canvas = expected
        return {"path": str(path), "sha256": "f" * 64, "frames": frames,
                "frameRate": rate, "width": canvas[0], "height": canvas[1]}

    def close(self) -> None:
        """Remove only the new metadata test directory owned by this fixture."""
        self.source.close()
