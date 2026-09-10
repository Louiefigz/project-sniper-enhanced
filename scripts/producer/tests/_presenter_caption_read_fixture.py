"""TEST held files/live stub-observer output; V8 selection is explicitly stubbed.

This is not source admission, decoded caption/presenter pixels, a stopped-worker
receipt or renderer qualification. The cold graph/observation/caption readers
are real; only V8 source-selection setup and original probe leaves are stubs.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import replace
import os
from pathlib import Path
import stat
from unittest.mock import patch

from _presenter_caption_clearance_fixture import ClearanceFixture
from cut_preview_io import digest
from guided_caption_layers import opening_caption_layers
from guided_caption_dependencies import hold_caption_file
from guided_opening_presenter import OpeningPresenterContext, _graph
from guided_presenter_caption_clearance import inspect_presenter_caption_clearance
from guided_presenter_caption_picture import presenter_caption_picture_record
from guided_presenter_capture_inputs import PresenterCaptureSelection
from guided_presenter_profile import PRESENTER_CAPTION_SHORT_PROFILE
from guided_presenter_read import PresenterReadContext
from headless.external_media_snapshot import ExternalMediaSnapshot, observe_external_media_snapshot
from headless.external_media_verification import SourceVerificationRuntime
from ingest_media_observation import SourceVerificationCapture, VerifiedExecutionMedia
from opening_prefix_contract import HeldPrefixInput


class _Clearance(ClearanceFixture):
    """Author the TEST timing before any caption plan bytes are compiled/held."""

    def __init__(self, span: tuple[int, int]) -> None:
        """Do not alter a held plan to obtain a crossing or future-window case."""
        self.span = span
        super().__init__("30/1")

    def window(self, _span: tuple[int, int], index: int = 7) -> object:
        """Keep the existing validated portrait manual geometry."""
        return super().window(self.span, index)


class CaptionReadFixture:
    """Join existing real TEST caption files and original tiny source identity."""

    def __init__(self, span: tuple[int, int] = (0, 120)) -> None:
        """Retain a genuine tiny hash pass, without adding an admission claim."""
        self.fixture = _Clearance(span)
        f = self.fixture
        asset = f.observed.graph_asset
        docs = {**f.inputs.documents, "frameBindings": {"graphics": []}, "readinessPacket": {
            "evidence": {"presenterPolicy": {"assets": [{"assetId": asset.asset_id,
                                                        "width": asset.width, "height": asset.height}]}}}}
        docs["authority"].update(core={"startFrame": 0, "endFrameExclusive": 60}, profile=PRESENTER_CAPTION_SHORT_PROFILE)
        self.inputs = replace(f.inputs, value={**f.inputs.value, "profile": PRESENTER_CAPTION_SHORT_PROFILE},
                              documents=docs, verified_media=self._capture())
        self.held = f.held
        base_path = f.root / "TEST-base-not-video.mp4"
        base_path.write_bytes(b"TEST tiny held base, never decoded")
        base = hold_caption_file(base_path, f.guard)
        self.base = HeldPrefixInput(base.path, base.sha256, base.size_bytes)
        self.read = PresenterReadContext(self.inputs, self.base, f.runtime.ffprobe, f.guard)
        self.selection = PresenterCaptureSelection(f.owner.selected, (f.probe.source,), "30/1")
        self.layers, caption_layers = opening_caption_layers([], self.held, 120)
        self.layers = (tuple(self.layers), caption_layers["captionTail"])
        self.pictures = self._pictures(caption_layers)

    def _capture(self) -> VerifiedExecutionMedia:
        """Read actual TEST source bytes once; no external receipt is fabricated."""
        f, source = self.fixture, self.fixture.probe.source
        runtime = SourceVerificationRuntime(f.probe.deadline.remaining)
        capture = SourceVerificationCapture(runtime)
        capture.add(observe_external_media_snapshot(ExternalMediaSnapshot(
            source.path, source.sha256, source.size_bytes, 0, 0), runtime))
        admission = f.selected.admission
        entry = {"lane": admission.lane, "mediaKind": admission.media_kind,
            "originalPath": admission.original_path, "snapshotPath": source.path,
            "sha256": source.sha256, "sizeBytes": source.size_bytes,
            "admissionReceiptPath": admission.receipt_path, "admissionReceiptSha256": admission.receipt_sha256}
        return capture.finish([entry])

    def _pictures(self, captions: dict) -> dict:
        """Keep real graph/report projections, with visibly synthetic range evidence."""
        f, authority = self.fixture, self.inputs.documents["authority"]
        context = OpeningPresenterContext(f.owner, self.inputs.documents["candidatePlan"], self.base)
        _opening, layers = _graph(context, authority, *self.layers)
        ranges = {name: {**authority[name], "TEST": "not decoded output"} for name in ("core", "review")}
        pictures = {"ranges": ranges, "captionLayers": captions,
                    "presenterLayers": {**layers, "pictureRangesHash": digest(ranges)}}
        report = inspect_presenter_caption_clearance(replace(f.context, inputs=self.inputs), f.guard)
        pictures["presenterCaptionClearance"] = presenter_caption_picture_record(report, pictures)
        return pictures

    @contextmanager
    def selected(self) -> Iterator[None]:
        """Stub only V8 selection; real graph, observation and held-cue readers run."""
        with patch("guided_presenter_caption_read.capture_selection", return_value=self.selection), \
                patch("guided_presenter_read.capture_selection", return_value=self.selection):
            yield

    def mutate_file(self, path: Path) -> None:
        """Append only to an exact TEST-owned, nonalias regular single-link file."""
        roots = (self.fixture.root, self.fixture.probe.root)
        prefixes = ("sniper-presenter-caption-TEST-", "sniper-presenter-probe-unit-")
        if any(root.resolve(strict=True) != root or root.parent != Path("/private/tmp")
               or not root.name.startswith(prefix) for root, prefix in zip(roots, prefixes)):
            raise AssertionError("TEST mutation roots are not their original canonical temporary roots")
        allowed = {Path(row.path) for row in self.held.files}
        allowed.update((Path(self.held.binding.plan.path), Path(self.read.ffprobe.path)))
        if path not in allowed or path.resolve(strict=True) != path \
                or not any(path != root and path.is_relative_to(root) for root in roots):
            raise AssertionError("TEST mutation target is outside the explicit owned file inventory")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AssertionError("TEST mutation target must be regular and single-link")
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            current = os.fstat(descriptor)
            if (current.st_dev, current.st_ino, current.st_nlink, current.st_mode) \
                    != (before.st_dev, before.st_ino, 1, before.st_mode):
                raise AssertionError("TEST mutation target changed before descriptor acquisition")
            raw = b"TEST deliberate owned-file mutation"
            if os.write(descriptor, raw) != len(raw):
                raise AssertionError("TEST mutation write was incomplete")
        finally:
            os.close(descriptor)

    def close(self) -> None:
        """Remove only this fixture's original tiny temporary directories."""
        self.fixture.close()
