"""Controlled real-media fixture for selected-source visual A/V mapping."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from edit.cut_repair_candidate_qc_types import (
    CandidateAuthority,
    DirtyWindow,
    QcRun,
    QcTools,
    ToolFile,
    VisualImplementationFile,
    VisualOracleTool,
)
from edit.cut_repair_candidate_qc_tools import (
    approved_visual_oracle_files,
)
from edit.cut_repair_context_sources import digest
from edit.cut_repair_visual_lip_sync_types import (
    FrameSpan,
    MediaAuthority,
    OracleRequest,
    OracleToolchain,
    RationalRate,
    RegionPpm,
    SampleSpan,
    SelectionAuthority,
    VISUAL_IMPLEMENTATION_NONCLAIMS,
    VISUAL_IMPLEMENTATION_SCOPE,
)

FFMPEG = shutil.which("ffmpeg")
ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = ROOT / "edit" / "cut_repair_visual_lip_sync.py"
POLICY = ROOT / "contracts" / "cut-repair-visual-lip-sync-policy-v1.json"


def file_hash(path: str | Path) -> str:
    """Hash one controlled fixture or pinned runtime file."""
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _run(command: list[str]) -> None:
    result = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1000:])


def _audio_source() -> str:
    amplitude = "0.08+0.35*mod(floor(t*30)*17\\,31)/31"
    return f"aevalsrc=({amplitude})*sin(2*PI*437*t):s=48000:d=2"


def _source(path: str, periodic: bool = False) -> None:
    if not FFMPEG:
        raise unittest.SkipTest("ffmpeg is unavailable")
    command = [
        FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=0x202838:s=320x240:r=30:d=2",
        "-f", "lavfi", "-i", "testsrc2=s=128x72:r=30:d=2",
        "-f", "lavfi", "-i", _audio_source(),
    ]
    inset = "[1:v]null"
    if periodic:
        inset = (
            "[1:v]trim=end_frame=2,loop=loop=29:size=2:start=0,"
            "setpts=N/(30*TB)")
    graph = f"{inset}[mouth];[0:v][mouth]overlay=96:120:shortest=1[v]"
    command.extend([
        "-filter_complex", graph, "-map", "[v]", "-map", "2:a:0",
        "-frames:v", "60", "-c:v", "libx264", "-crf", "10",
        "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", "-y", path,
    ])
    _run(command)


def _candidate(source: str, path: str, mode: str) -> None:
    video = (
        "trim=start_frame=0:end_frame=60,setpts=PTS-STARTPTS")
    if mode == "occluded":
        video += ",drawbox=x=96:y=120:w=128:h=72:color=black:t=fill"
    audio = "atrim=start_sample=0:end_sample=96000,asetpts=PTS-STARTPTS"
    if mode == "delayed":
        audio += ",adelay=100,apad,atrim=end_sample=96000"
    _run([
        str(FFMPEG), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", source, "-filter_complex",
        f"[0:v]{video}[v];[0:a]{audio}[a]",
        "-map", "[v]", "-map", "[a]", "-frames:v", "60",
        "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p",
        "-c:a", "pcm_s16le", "-y", path,
    ])


class VisualLipSyncFixture:
    """Source and full-plan candidates derived from its exact selected ranges."""

    def __init__(self) -> None:
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="p2-visual-qc-"))
        self.source = os.path.join(self.root, "selected-take.mov")
        self.periodic_source = os.path.join(
            self.root, "periodic-selected-take.mov")
        _source(self.source)
        _source(self.periodic_source, True)
        self.candidates = {}
        for mode in ("aligned", "delayed", "occluded"):
            path = os.path.join(self.root, f"{mode}-candidate.mov")
            _candidate(self.source, path, mode)
            self.candidates[mode] = path
        periodic = os.path.join(self.root, "periodic-candidate.mov")
        _candidate(self.periodic_source, periodic, "aligned")
        self.candidates["periodic"] = periodic

    @staticmethod
    def _tools() -> OracleToolchain:
        runtime = os.path.realpath(sys.executable)
        implementation = os.path.realpath(IMPLEMENTATION)
        policy = os.path.realpath(POLICY)
        ffmpeg = os.path.realpath(str(FFMPEG))
        files = tuple(
            (role, path, file_hash(path))
            for role, path in approved_visual_oracle_files())
        closure = digest([
            {"role": role, "path": path, "sha256": value_hash}
            for role, path, value_hash in files])
        return OracleToolchain(
            ffmpeg, file_hash(ffmpeg), runtime, file_hash(runtime),
            implementation, file_hash(implementation),
            VISUAL_IMPLEMENTATION_SCOPE,
            VISUAL_IMPLEMENTATION_NONCLAIMS,
            policy, file_hash(policy), closure, files)

    def _selection(
        self,
        source: str,
        region: RegionPpm,
    ) -> SelectionAuthority:
        return SelectionAuthority(
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "candidate-visible-take-1", "raw-selected-take", source,
            file_hash(source), FrameSpan(0, 60),
            SampleSpan(0, 96_000, 48_000), RationalRate(30, 1),
            FrameSpan(0, 60), SampleSpan(0, 96_000, 48_000),
            RationalRate(30, 1), region)

    def request(
        self,
        mode: str,
        region: RegionPpm | None = None,
    ) -> OracleRequest:
        """Bind one candidate that was physically rendered from selected bytes."""
        source = self.periodic_source if mode == "periodic" else self.source
        candidate = self.candidates[mode]
        selected_region = region or RegionPpm(300_000, 500_000, 400_000, 300_000)
        return OracleRequest(
            self._selection(source, selected_region),
            MediaAuthority(candidate, file_hash(candidate)),
            self._tools(), "6" * 64)

    @staticmethod
    def _selection_receipt(selected: SelectionAuthority) -> dict:
        return {
            "receiptHash": selected.receipt_hash,
            "candidateSetHash": selected.candidate_set_hash,
            "selectionHash": selected.selection_hash,
            "selectedCandidateId": selected.selected_candidate_id,
            "sourceId": selected.source_id,
            "sourceMediaPath": selected.source_path,
            "sourceMediaSha256": selected.source_sha256,
            "sourceFrameRange": {
                "firstFrame": 0, "endFrameExclusive": 60,
                "fpsNumerator": 30, "fpsDenominator": 1,
            },
            "sourceSampleRange": {
                "startSample": 0, "endSampleExclusive": 96_000,
                "sampleRate": 48_000,
            },
            "outputFrameRange": {
                "firstFrame": 0, "endFrameExclusive": 60,
            },
            "visualSpeechRegion": {
                "xPpm": 300_000, "yPpm": 500_000,
                "widthPpm": 400_000, "heightPpm": 300_000,
            },
        }

    def _authority(
        self,
        request: OracleRequest,
        selection: dict,
    ) -> CandidateAuthority:
        selected = request.selection
        return CandidateAuthority(
            self.root, selected.preparation_hash,
            {
                "reviewCandidateDescriptorHash": "7" * 64,
                "reviewCandidateDescriptorPath":
                    os.path.join(self.root, "candidate.json"),
            },
            {"operationHash": selected.operation_hash},
            request.candidate.path, request.candidate.sha256, {},
            "controlled visible phrase", ("word-1",),
            selected.source_path, selected.source_sha256,
            selected.source_id, 0, 96_000, 48_000, 60,
            DirtyWindow(0, 60, 0, 96_000, 0, 96_000, 48_000, 30, 1),
            True, selection, selected.receipt_hash,
            os.path.join(self.root, "alternate-take-selection.json"),
        )

    @staticmethod
    def _qc_tools(
        request: OracleRequest,
        visual_tool: bool,
    ) -> QcTools:
        oracle = request.tools
        visual = VisualOracleTool(
            "deterministic-selected-source-av-offset-v1",
            ToolFile(oracle.runtime_path, oracle.runtime_sha256),
            ToolFile(
                oracle.implementation_path, oracle.implementation_sha256),
            oracle.implementation_scope,
            oracle.implementation_nonclaims,
            ToolFile(oracle.policy_path, oracle.policy_sha256),
            oracle.implementation_closure_hash,
            tuple(
                VisualImplementationFile(
                    role, ToolFile(path, value_hash))
                for role, path, value_hash
                in oracle.implementation_files),
        ) if visual_tool else None
        return QcTools(
            request.tool_manifest_hash,
            ToolFile(oracle.ffmpeg_path, oracle.ffmpeg_sha256),
            ToolFile(oracle.runtime_path, oracle.runtime_sha256),
            ToolFile(oracle.policy_path, oracle.policy_sha256),
            None, visual,
        )

    def qc_run(
        self,
        mode: str = "aligned",
        visual_tool: bool = True,
    ) -> QcRun:
        """Project controlled source/candidate bytes through candidate QC types."""
        request = self.request(mode)
        selection = self._selection_receipt(request.selection)
        authority = self._authority(request, selection)
        return QcRun(
            authority, self._qc_tools(request, visual_tool),
            "8" * 64, self.root)

    def clean(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
