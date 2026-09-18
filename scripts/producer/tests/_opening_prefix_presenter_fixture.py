"""Explicit fake observation metadata for pure prefix faults, never real media."""
from __future__ import annotations

import subprocess
from dataclasses import replace
from fractions import Fraction
from unittest.mock import patch

from _guided_presenter_observation_fixture import ObservationFixture
from graphics.presenter_layout_contract import PresenterCanvas
from graphics.presenter_layout_geometry import compile_presenter_geometry
from graphics.presenter_layout_graph import PresenterGraphSpec, PresenterGraphWindow
from guided_presenter_observation import observe_presenter_asset
from opening_prefix_contract import (CompositorPrefixRequest, HeldPrefixInput, PrefixClock,
                                     PrefixRanges, PrefixOracleRuntime, PrefixDeadline, verify_held_input)
from opening_prefix_presenter import PrefixPresenterGraphs
from test_opening_prefix_contract import held
from test_presenter_layout_graph import declaration


class PrefixPresenterFixture:
    """Actual small files and stubbed decoded facts; no source admission claim."""

    def __init__(self, image: bool = True, rate: str = "30000/1001") -> None:
        """Return actual observer control-flow output with only its leaf stubbed."""
        self.fixture = ObservationFixture(image)
        self.root = self.fixture.root
        fps = Fraction(rate)
        for document in (self.fixture.header, self.fixture.frames):
            document["streams"][0].update(r_frame_rate=rate, avg_frame_rate=rate, time_base=f"1/{fps.numerator}")
        for index, frame in enumerate(self.fixture.frames["frames"]):
            frame.update(pts=index * fps.denominator, best_effort_timestamp=index * fps.denominator,
                         duration=fps.denominator)
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.fixture.raw()]
        with patch("guided_presenter_observation.run_text", side_effect=results):
            self.observed = observe_presenter_asset(self.fixture.selected, self.fixture.source, rate, self.fixture.runtime)
        base = self.root / "TEST-base-not-media"
        base.write_bytes(b"TEST metadata-only base")
        canvas = PresenterCanvas(64, 36, 48, "yuv420p")
        windows = tuple(PresenterGraphWindow(index, compile_presenter_geometry(declaration(), canvas, span),
                                            self.observed.graph_asset) for index, span in ((3, (2, 18)), (7, (30, 42))))
        full = PresenterGraphSpec(canvas, str(fps), windows, "bt709-limited-video")
        assets = (HeldPrefixInput(self.observed.source.path, self.observed.source.sha256, self.observed.source.size_bytes),)
        self.guard_calls = 0
        presenter = PrefixPresenterGraphs(full, replace(full, windows=windows[:1]), assets, (self.observed,), self.guard)
        self.request = CompositorPrefixRequest(held(base), (), (), (), PrefixClock(rate, 48, 64, 36),
            PrefixRanges((3, 9), (0, 12)), presenter=presenter)
        tool = held(self.root / "TEST-ffprobe")
        self.runtime = PrefixOracleRuntime(tool, tool, str(self.root), 30)

    def guard(self) -> None:
        """Count phase boundaries without pretending they are a production lease."""
        self.guard_calls += 1

    def identities(self) -> dict[str, tuple]:
        """Use actual production full-byte hashing of these tiny TEST files."""
        rows = (self.request.base, *self.request.presenter.assets, self.runtime.ffprobe)
        return {row.path: verify_held_input(row, PrefixDeadline(5)) for row in rows}

    def close(self) -> None:
        """Release only this new disposable pure-test tree."""
        self.fixture.close()
