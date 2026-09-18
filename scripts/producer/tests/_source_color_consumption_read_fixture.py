"""Real TEMP generated files and parsers, explicit TEST provenance/native leaves.

No source admission, full-source observation, renderer or user approval is
claimed. The independently supplied observation section is fabricated TEST
data. Only ffprobe's subprocess leaf is stubbed; actual packet/copy parsers run.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from unittest.mock import patch

from _source_color_observation_contract_fixture import ObservationContractFixture
from compile_timeline import compile_plan
from cross_runtime_canonical_json import canonical_compact_json
from cut_elementary_proof import ElementaryStream, SequenceProof
import cut_manifestation_authority as manifest
from cut_preview_io import digest, file_hash
from fingerprints import plan_content_hash
from guided_source_color_consumption_contract import CONSUMPTION_SCOPE, EVIDENCE_SCOPE
from guided_source_color_consumption_files import SourceColorConsumptionReadContext
from guided_source_color_consumption_records import join_manifestation


class ConsumptionReadFixture:
    """Exact owned artifact allowlist and independent synthetic worker attestations."""

    def __init__(self) -> None:
        """Make only private disposable directories and new-only TEST leaf files."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-consumption-read-", dir="/private/tmp")
        self.directory = Path(self.temp.name).resolve()
        self.root, self.base = self.directory / "media-output", self.directory / "media-output/full-program-base"
        self.bus = self.base / ".source-float-v2-TEST"
        self.tools = self.directory / "tools"
        for path in (self.root, self.base, self.bus, self.tools):
            path.mkdir(mode=0o700)
        self.paths = {"evidence": self.root / "source-color-evidence.json", "base": self.base / "final.mp4",
            "timelineMap": self.base / "timeline_map.json", "cutManifestation": self.base / manifest.MANIFESTATION_NAME,
            "sourceBus": self.bus / "bus-receipt.json", "sourceFloatMaster": self.bus / "master-receipt.json",
            "pictureMaster": self.bus / "picture-master.mp4", "ffprobe": self.tools / "ffprobe"}
        self.allowed = frozenset(self.paths.values())
        self._new(self.paths["base"], b"TEST final inert video")
        self._new(self.paths["pictureMaster"], b"TEST master inert video")
        self._new(self.paths["ffprobe"], b"#!/TEST-never-executed\n")
        self.paths["ffprobe"].chmod(0o500)
        self.original = ObservationContractFixture()
        self.inputs, self.observations = self.original.inputs, self.original.section
        self.observations["opening"]["claimPath"] = str(self.directory / "execution-claim.json")
        self._plan()
        self.manifestation, self.cuts = self._cuts()
        self.consumed = self._consumption()
        self._records()
        self.calls, self.native_calls = 0, []
        self.on_guard = lambda: None
        self.context = SourceColorConsumptionReadContext(self.inputs, self.bindings, time.monotonic() + 60, self.guard)

    def cleanup(self) -> None:
        """Remove only the owning standard TEMP directory, never shared code or sources."""
        self.temp.cleanup()

    def _new(self, path: Path, raw: bytes) -> None:
        """Publish exact allowlisted new-only fixture files beneath canonical private parents."""
        if path not in self.allowed or path.parent.resolve(strict=True) != path.parent:
            raise AssertionError("TEST creation escaped exact artifact allowlist")
        with path.open("xb") as stream:
            stream.write(raw)

    def raw(self, value: dict) -> bytes:
        """Use the actual strict JSON domain and existing receipt byte spelling."""
        return canonical_compact_json(value).encode("utf8")

    def ref(self, path: Path) -> dict:
        """Observe only exact existing generated TEST artifact refs, never original sources."""
        return {"path": str(path), "sha256": file_hash(path), "sizeBytes": path.stat().st_size}

    def _plan(self) -> None:
        """Preserve repeated-source ordering and real compiler floating second semantics."""
        cuts = [{"sourceId": name, "start": 0, "end": .25, "speed": 1} for name in ("raw-b", "raw-a", "raw-b")]
        self.plan = {"target": {"mode": "longform", "fps": 24, "width": 1920, "height": 1080}, "cutTrack": cuts}
        self.inputs.documents.update(candidatePlan=self.plan, acceptedPlan=deepcopy(self.plan),
            authority={"frameRate": "24", "totalFrames": 18, "target": {"width": 1920, "height": 1080}})
        self.timeline = compile_plan(self.plan).to_dict()
        self._new(self.paths["timelineMap"], json.dumps(self.timeline, indent=2).encode("utf8"))

    def _cuts(self) -> tuple:
        """Use actual closed manifestation builder with only native/elementary leaves stubbed."""
        paths = [str(self.base / "work/cut-parts" / f"part_{index:04d}.mp4") for index in range(3)]
        concat = str(self.base / "work/mezzanine.mp4")
        proof = {"videoDuration": .75, "expectedDuration": .75, "videoFrames": 18,
            "driftFrames": 0.0, "toleranceFrames": 2.5, "segments": 3}
        sequence = SequenceProof([ElementaryStream("a" * 64, 12)] * 3,
            ElementaryStream("b" * 64, 36), ElementaryStream("b" * 64, 36))
        artifact = lambda path: {"path": path, "sha256": "c" * 64, "videoFrames": 18 if path == concat else 6}
        with patch.object(manifest, "prove_video_sequence", return_value=sequence), patch.object(manifest, "_artifact", side_effect=artifact):
            result = manifest.write_manifestation(manifest.ManifestationInputs(self.plan, str(self.paths["timelineMap"]), paths, concat, "24/1", proof))
        by_id = {row["sourceId"]: row for row in self.observations["sources"]}
        rows = [self._cut(index, segment, (paths[index], by_id[segment["source_id"]])) for index, segment in enumerate(self.timeline["segments"])]
        return result, rows

    def _cut(self, index: int, segment: dict, original: tuple) -> dict:
        """Build one independent original worker command attestation, not a live token."""
        output, observed = original
        source = {"path": observed["source"]["path"], "sha256": observed["source"]["sha256"],
            **{key: observed["binding"][key] for key in ("admissionReceiptSha256", "declarationSha256")}}
        return {"segment": segment, "source": source, "sourcePath": source["path"], "outputPath": output,
            "profile": {"width": 1920, "height": 1080, "frameRate": "24/1", "pixelFormat": "yuv420p"},
            "framesBefore": index * 6, "frames": 6, "argv": ["TEST-not-executable", "-i", source["path"], output]}

    def _consumption(self) -> dict:
        """Make bounded JSON attested metadata; actual readback must independently join it."""
        joined = join_manifestation(self.manifestation, (self.plan, self.timeline, self.cuts, tuple(row["outputPath"] for row in self.cuts)))
        joined["concatPath"] = str(self.base / "work/mezzanine.mp4")
        picture = self.paths["pictureMaster"]
        master = {"inputPath": joined["concatPath"], "outputPath": str(picture), "ass": None,
            "fps": 24, "fpsExact": None, "duration": .75, "frameCount": 18, "cover": None,
            "argv": ["TEST-not-executable", "-i", joined["concatPath"], str(picture)]}
        return {"scope": CONSUMPTION_SCOPE, "cuts": self.cuts, "manifestation": joined, "master": master,
            "pictureCopy": {"picturePacketsIdentical": True, "picturePackets": 18, "pictureTimeBase": "1/24000",
                            "pictureSourceSha256": file_hash(picture)}, "colorQualified": False, "deliveryApproved": False}

    def _records(self) -> None:
        """Publish ordinary raw master/bus semantics and original source evidence refs."""
        bus = {"kind": "ordinary-source-float-bus", "audioClockPolicy": "source-float-v2", "planHash": plan_content_hash(self.plan)}
        bus["receiptHash"] = digest(bus)
        self._new(self.paths["sourceBus"], self.raw(bus))
        master = {"schemaVersion": 2, "kind": "ordinary-source-float-master", "approved": False,
            "audioClockPolicy": "source-float-v2", "busReceiptHash": bus["receiptHash"], "masteringPolicyVersion": "TEST",
            "planHash": bus["planHash"], "path": str(self.paths["base"]), "sha256": file_hash(self.paths["base"]),
            "picture": self.consumed["pictureCopy"], "audioClock": {}, "filter": "TEST", "delivery": {},
            "audiblePathAacEncodes": 1, "legacyPictureTransportAacStillExecuted": True}
        master["receiptHash"] = digest(master)
        self._new(self.paths["sourceFloatMaster"], self.raw(master))
        self.consumed["basePublication"] = {"receiptPath": str(self.paths["sourceFloatMaster"]), "receipt": master}
        full = {key: self.ref(self.paths[key]) for key in ("base", "timelineMap", "cutManifestation", "sourceFloatMaster")}
        self.evidence = {"schemaVersion": 1, "kind": "guided-opening-source-color-media-evidence", "scope": EVIDENCE_SCOPE,
            "observations": self.observations, "pictureConsumption": self.consumed, "fullProgram": full,
            "gamutMeasured": False, "gradeApplied": False, "colorQualified": False, "openingApproved": False, "deliveryApproved": False}
        self.evidence["receiptHash"] = digest(self.evidence)
        self._new(self.paths["evidence"], self.raw(self.evidence) + b"\n")
        self.evidence = json.loads(self.raw(self.evidence))
        self.consumed, self.observations = self.evidence["pictureConsumption"], self.evidence["observations"]
        self.bindings = {"evidenceRef": {**self.ref(self.paths["evidence"]), "receiptHash": self.evidence["receiptHash"]},
            "fullProgram": {"base": full["base"], "receipts": {"timelineMap": full["timelineMap"],
                "cutManifestation": full["cutManifestation"], "sourceBus": self.ref(self.paths["sourceBus"])}},
            "observations": self.observations, "outputRoot": str(self.root),
            "tools": {"ffprobe": {"path": str(self.paths["ffprobe"]), "sha256": file_hash(self.paths["ffprobe"])}}}

    def change(self, path: Path, raw: bytes) -> None:
        """Fault writes touch only canonical allowlisted regular single-link owned TEMP files."""
        info = path.lstat()
        if path not in self.allowed or path.resolve(strict=True) != path or not path.is_relative_to(self.directory) \
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise AssertionError("TEST mutation escaped exact owned artifact")
        path.write_bytes(raw)

    def reseal(self) -> None:
        """Let pure negative fixtures change attested data BEFORE read entry, never during holds."""
        self.evidence["receiptHash"] = digest({key: row for key, row in self.evidence.items() if key != "receiptHash"})
        self.change(self.paths["evidence"], self.raw(self.evidence) + b"\n")
        self.bindings["evidenceRef"] = {**self.ref(self.paths["evidence"]), "receiptHash": self.evidence["receiptHash"]}

    def guard(self) -> None:
        """Explicit TEST original tool/source admission callback, no real admission claimed."""
        self.calls += 1
        self.on_guard()

    def native(self, argv: list[str]) -> subprocess.CompletedProcess:
        """Return only synthetic ffprobe stdout; actual packet/CFR/copy parsers are unchanged."""
        self.native_calls.append(tuple(argv))
        if argv[-1] not in {str(self.paths["pictureMaster"]), str(self.paths["base"])}:
            raise AssertionError("TEST native opened an unowned source or command")
        stream = {"time_base": "1/24000", "r_frame_rate": "24/1", "avg_frame_rate": "24/1"}
        packets = [{"pts": index * 1000, "duration": 1000, "data_hash": "SHA256:" + "d" * 64} for index in range(18)]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"streams": [stream], "packets": packets}), "")
