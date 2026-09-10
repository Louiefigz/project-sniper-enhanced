"""TEST original-worker projections over stub probes, not authenticated receipts."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
from unittest.mock import patch

from _guided_presenter_capture_fixture import PresenterCaptureFixture, bind_capture_documents
from _guided_presenter_observation_fixture import ObservationFixture, held
from cut_preview_io import digest
from guided_opening_presenter import OpeningPresenterContext, _graph
from guided_presenter_capture import PresenterCaptureContext, acquire_presenter_execution
from guided_presenter_probe_identity import presenter_stat_identity
from guided_presenter_read import PresenterReadContext
from guided_proposal_presenter import guided_presenter_policy
from headless.external_media_snapshot import ExternalMediaSnapshot, observe_external_media_snapshot
from headless.external_media_verification import SourceVerificationRuntime, assert_verified_snapshots
from ingest_media_observation import SourceVerificationCapture
from opening_prefix_contract import HeldPrefixInput


class _CaptureFixture(PresenterCaptureFixture):
    """Reuse real V8 metadata and tiny same-pass identities for either picture kind."""

    def __init__(self, image: bool) -> None:
        """Use the original TEST stub tool and never invoke an actual decoder."""
        self.probe = ObservationFixture(image)
        self.inputs = self._inputs(True)
        tool = self.probe.runtime.ffprobe
        self.context = PresenterCaptureContext({"ffprobe": {"path": tool.path, "sha256": tool.sha256}},
            str(self.probe.root), self.probe.deadline, lambda: None)

    def _manifest(self) -> tuple[dict, dict]:
        """Correct inherited TEST metadata for an explicitly tagged PNG fixture."""
        manifest, entry = super()._manifest()
        if self.probe.selected.admission.media_kind == "still-image":
            manifest["broll"][0].update(kind="image", duration=None)
        return manifest, entry

    def add_second_asset(self) -> None:
        """Add distinct tiny TEST bytes and truthful capture, never another media decode."""
        raw = b"TEST second source, not an actual video"
        sha = hashlib.sha256(raw).hexdigest()
        path = self.probe.path.parent / f"{sha}.media"
        path.write_bytes(raw)
        docs, captured = self.inputs.documents, self.inputs.verified_media
        asset = {**docs["manifest"]["broll"][0], "id": "TEST-second", "path": str(path),
                 "originalPath": "/TEST/second.mp4", "sourceSha256": sha, "sourceSizeBytes": len(raw)}
        docs["manifest"]["broll"].append(asset)
        packet = docs["readinessPacket"]
        packet["evidence"]["presenterPolicy"] = guided_presenter_policy(docs["acceptedPlan"], docs["manifest"])
        packet["proposal"]["operations"][1]["presenterLayout"]["assetId"] = asset["id"]
        docs["candidatePlan"]["presenterLayouts"][1]["layout"]["assetId"] = asset["id"]
        bind_capture_documents(docs)
        runtime = SourceVerificationRuntime(self.probe.deadline.remaining)
        capture = SourceVerificationCapture(runtime)
        capture.add(captured.snapshots[0])
        capture.add(observe_external_media_snapshot(ExternalMediaSnapshot(str(path), sha, len(raw), 0, 0), runtime))
        entries = captured.entries()
        entries.append({**entries[0], "originalPath": asset["originalPath"], "snapshotPath": str(path),
                        "sha256": sha, "sizeBytes": len(raw)})
        self.inputs = replace(self.inputs, verified_media=capture.finish(entries))


class PresenterReadFixture:
    """Acquire a genuine live control-flow return with only decoder leaves stubbed."""

    def __init__(self, image: bool = False, two_assets: bool = False) -> None:
        """Retain original projection before closing its live execution lifetime."""
        self.capture = _CaptureFixture(image)
        if two_assets:
            self.capture.add_second_asset()
        self.inputs, self.probe = self.capture.inputs, self.capture.probe
        base_path = self.probe.root / "TEST-original-base.mp4"
        base_path.write_bytes(b"TEST independently held base, not decoded picture")
        base = held(base_path)
        self.base = HeldPrefixInput(base.path, base.sha256, base.size_bytes)
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.probe.raw()] * (2 if two_assets else 1)
        with patch("guided_presenter_observation.run_text", side_effect=results), \
                acquire_presenter_execution(self.inputs, self.capture.context) as owner:
            context = OpeningPresenterContext(owner, self.inputs.documents["candidatePlan"], self.base)
            _opening, record = _graph(context, self.inputs.documents["authority"], (), None)
            self.tool = owner.runtime.ffprobe
        self.records = record["observations"]
        ranges = {name: {"TEST": "actual output decode is deliberately outside this fixture"} for name in ("core", "review")}
        self.pictures = {"ranges": ranges, "presenterLayers": {**record, "pictureRangesHash": digest(ranges)}}
        self.context = PresenterReadContext(self.inputs, self.base, self.tool, self.guard)

    def guard(self) -> None:
        """Borrow the original TEST deadline and cheap original source/tool identities."""
        runtime = SourceVerificationRuntime(self.probe.deadline.remaining)
        assert_verified_snapshots(self.inputs.verified_media.snapshots, runtime)
        if presenter_stat_identity(Path(self.tool.path).lstat()) != self.tool.stat_identity:
            raise RuntimeError("TEST held probe changed")
        runtime.check()

    def noop_context(self) -> PresenterReadContext:
        """Keep genuine absent-layout V8 semantics without source acquisition."""
        return replace(self.context, inputs=self.capture.noop(), guard=self.probe.deadline.remaining)

    def close(self) -> None:
        """Dispose of only this small explicit TEST fixture directory."""
        self.capture.close()
