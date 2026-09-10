"""Actual encode hooks/writer and cold reader joined over exact owned TEST files.

Source admission, decoded observations, audio delivery and selection remain the
inherited explicit TEST leaves. No native process runs. Unlike the older writer
fixture, artifact roles and raw compiler JSON match the production renderer.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import subprocess
from unittest.mock import patch

from _source_color_media_evidence_fixture import SourceColorMediaEvidenceFixture
from audio import audio_mix_picture
from cross_runtime_canonical_json import canonical_compact_json
from cut_manifestation_authority import MANIFESTATION_NAME, _receipt_hash
from cut_preview_io import file_hash
from fingerprints import plan_content_hash
from guided_source_color_consumption_read import SourceColorConsumptionReadContext
import render


class ConsumptionIntegrationFixture(SourceColorMediaEvidenceFixture):
    """Retain the actual source holder and original clock across live/cold paths."""

    def __init__(self, pins: list[dict]) -> None:
        """Install production-shaped generated roles before any encode artifact is held."""
        super().__init__(pins)
        self.bus_dir, self.tools = self.base / ".source-float-v2-TEST", self.root / "TEST-tools"
        self.bus_dir.mkdir(mode=0o700)
        self.tools.mkdir(mode=0o700)
        self.bus_path = self.bus_dir / "bus-receipt.json"
        self.picture_path, self.master_path = self.bus_dir / "picture-master.mp4", self.bus_dir / "master-receipt.json"
        self.ffprobe = self.tools / "ffprobe"
        self.allowed.update({self.bus_path, self.picture_path, self.master_path, self.ffprobe})
        self._new(self.picture_path, b"TEST inert picture-master, not decoded video")
        self._new(self.ffprobe, b"#!/TEST-never-executed\n")
        self.ffprobe.chmod(0o500)
        self.original_bus, self.original_observed = self.live.bus, self.live.observed
        self.original_master_leaves = self.live.master_leaves
        self.live.bus, self.live.observed = self.bus, self.observed
        self.live.master_leaves = self.master_leaves
        self.native_calls = []
        self._target(self.timeline)
        with patch.object(render, "emit"):
            render.compile_stage(self.live.ctx)

    def _target(self, path: Path) -> None:
        """Authorize only this exact canonical, regular, single-link, owned TEST leaf."""
        info = path.lstat()
        if path not in self.allowed or path.resolve(strict=True) != path or not path.is_relative_to(self.root) \
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise AssertionError("TEST target escaped exact owned output")

    def change(self, path: Path, data: bytes) -> None:
        """Fault writes never follow a source, dependency or arbitrary inherited path."""
        self._target(path)
        path.write_bytes(data)

    def _new(self, path: Path, raw: bytes) -> None:
        """Create only allowlisted new-only leaves below existing private fixture parents."""
        if path not in self.allowed or path.parent.resolve(strict=True) != path.parent \
                or not path.is_relative_to(self.root):
            raise AssertionError("TEST creation escaped exact output role")
        with path.open("xb") as stream:
            stream.write(raw)

    def manifestation(self, inputs: object) -> dict:
        """Keep actual builder semantics and the producer's ordinary JSON float spelling."""
        record = self.original_manifestation(inputs)
        record["timelineMapSha256"] = file_hash(self.timeline)
        record["receiptHash"] = _receipt_hash(record)
        self._new(self.base / MANIFESTATION_NAME, json.dumps(record, indent=2).encode("utf8"))
        return record

    def bus(self) -> object:
        """Shape-only audio provenance keeps real SourceAudioBus and production artifact roles."""
        original = self.original_bus()
        plan_hash = plan_content_hash(self.source.inputs.documents["candidatePlan"])
        body = {"kind": "ordinary-source-float-bus", "audioClockPolicy": "source-float-v2", "planHash": plan_hash}
        receipt = {**body, "receiptHash": _receipt_hash(body)}
        self._new(self.bus_path, canonical_compact_json(receipt).encode("utf8"))
        admission = replace(original.admission, plan_hash=plan_hash)
        result = replace(original, directory=str(self.bus_dir), path=str(self.bus_dir / "TEST-dialogue.wav"),
                         receipt=receipt, admission=admission)
        self.live.ctx.audio_admission, self.live.ctx.source_audio_bus = admission, result
        return result

    def observed(self, path: str, duration: float) -> object:
        """Synthetic native packets bind the actual owned inert picture bytes, not a guessed SHA."""
        if Path(path) != self.picture_path:
            raise AssertionError("TEST picture observation escaped exact role")
        result = replace(self.original_observed(path, duration), sha256=file_hash(self.picture_path))
        self.live.picture = result
        return result

    def master_leaves(self, stack: ExitStack) -> dict:
        """Retain existing native stubs while checking the exact generated picture hash."""
        result = self.original_master_leaves(stack)
        stack.enter_context(patch.object(audio_mix_picture, "file_sha256", side_effect=self.picture_hash))
        return result

    def picture_hash(self, path: str) -> str:
        """Adapt the existing string API only to the exact owned generated picture file."""
        if Path(path) != self.picture_path:
            raise AssertionError("TEST native hash escaped original generated picture")
        self._target(self.picture_path)
        return file_hash(self.picture_path)

    def seal(self, path: str, body: dict) -> dict:
        """Publish actual ordinary master shape and canonical no-newline bytes in its bus directory."""
        if Path(path) != self.master_path:
            raise AssertionError("TEST master publisher escaped exact role")
        record = {**body, "receiptHash": _receipt_hash(body)}
        self._new(self.master_path, canonical_compact_json(record).encode("utf8"))
        self.live.sealed = record
        return record

    def ready(self) -> object:
        """Use the actual cut/master flow; label full audio/selection provenance as TEST-only."""
        prepared = super().ready()
        receipts = {**prepared.evidence["receipts"], "sourceBus": self.ref(self.bus_path)}
        return replace(prepared, evidence={**prepared.evidence, "receipts": receipts})

    def ref(self, path: Path) -> dict:
        """Read exact generated TEST bytes only, never original source or dependency contents."""
        self._target(path)
        return {"path": str(path), "sha256": file_hash(path), "sizeBytes": path.stat().st_size}

    def read_context(self, ref: dict, prepared: object, observations: dict) -> SourceColorConsumptionReadContext:
        """Borrow the original unrenewed clock; observation provenance is an explicit TEST boundary."""
        bindings = {"evidenceRef": ref, "fullProgram": prepared.evidence, "observations": observations,
                    "outputRoot": str(self.root), "tools": {"ffprobe": {
                        "path": str(self.ffprobe), "sha256": file_hash(self.ffprobe)}}}
        return SourceColorConsumptionReadContext(self.source.inputs, bindings, self.source.clock.end,
                                                self.context.assert_current)

    def native(self, argv: list[str]) -> subprocess.CompletedProcess:
        """Only generated-picture ffprobe stdout is synthetic; actual packet/copy parsers run."""
        if argv[-1] not in {str(self.picture_path), str(self.base_path)}:
            raise AssertionError("TEST native input escaped exact generated picture roles")
        self.native_calls.append(tuple(argv))
        stream = {"time_base": "1/24", "r_frame_rate": "24/1", "avg_frame_rate": "24/1"}
        packets = [{"pts": index, "duration": 1, "data_hash": "SHA256:" + "d" * 64} for index in range(18)]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"streams": [stream], "packets": packets}), "")
