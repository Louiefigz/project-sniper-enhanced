"""Controlled real project seed for the integrated P2 row-10 lifecycle."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from edit.compatibility_projection import build_projection
from edit.cut_repair_context_sources import (
    canonical_bytes,
    digest,
    source_rows,
    transcript,
)
from fingerprints import file_sha256, plan_content_hash
from tests._p2_row10_context_evidence import materialize_context_evidence
from tests._p2_surgical_terminal_fixture import publish_parent_active
from tests.test_p2_cut_repair_picture_prepare_media import (
    _PictureFixture,
    _write,
)

_PICTURE_LOCK = "7" * 64
_TARGET = {"phrase": "restore this phrase", "occurrence": 2}


def _word_rows(start: float) -> list[dict]:
    return [{
        "word": word,
        "start": start + index * 0.2,
        "end": start + (index + 1) * 0.2,
    } for index, word in enumerate(("restore", "this", "phrase"))]


def _json_file(path: str, value: object) -> str:
    payload = canonical_bytes(value)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(payload)
    return __import__("hashlib").sha256(payload).hexdigest()


def _active_graph(producer: str, graph_hash: str) -> tuple[dict, str, dict]:
    root = os.path.join(
        producer, ".render-graph-v1", "generations", graph_hash)
    graph = json.loads(Path(root, "graph.json").read_text())
    active = json.loads(Path(
        producer, ".render-graph-v1", "ACTIVE.json").read_text())
    receipt_hash = active["receiptHash"]
    receipt = json.loads(Path(
        root, "receipts", f"{receipt_hash}.json").read_text())
    return graph, receipt_hash, receipt


class Row10LifecycleFixture(_PictureFixture):
    """One admitted source with an omitted unique later three-word take."""

    def __init__(self) -> None:
        super().__init__(captions=False)
        self.whisper, self.whisper_model = self._whisper_tools()

    def _source_media(self) -> None:
        audio = (
            "(0.08+0.35*mod(floor(t*30)*floor(t*30)*73"
            "+floor(t*30)*19+11\\,997)/997)*sin(2*PI*480*t)")
        subprocess.run([
            str(__import__("shutil").which("ffmpeg")),
            "-y", "-nostdin", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=5",
            "-f", "lavfi", "-i", f"aevalsrc={audio}:s=48000:d=5",
            "-frames:v", "150", "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s32le", "-ar", "48000", "-ac", "2", "-shortest",
            self.source,
        ], check=True, capture_output=True)

    def _directive(self) -> str:
        transcript_path = os.path.join(
            self.source_dir, "raw.transcript.json")
        _write(transcript_path, {"transcript": [
            {
                "speaker": "host", "start": 0.4, "end": 1.0,
                "text": "restore this phrase.", "words": _word_rows(0.4),
            },
            {
                "speaker": "host", "start": 2.0, "end": 2.6,
                "text": "restore this phrase.", "words": _word_rows(2.0),
            },
        ]})
        path = os.path.join(self.root, "directive.json")
        _write(path, {
            "schemaVersion": 1, "operation": "cut.restoreSpeech",
            "mode": "analyze", "target": _TARGET,
        })
        return path

    def _plan(self) -> tuple[dict, str]:
        value = {
            "planVersion": 1,
            "target": {
                "mode": "longform", "scope": "trim", "fps": 30,
                "excerpt": True,
            },
            "cutTrack": [
                {"id": "seg-a", "sourceId": "raw",
                 "start": 4, "end": 5, "speed": 1},
                {"id": "seg-b", "sourceId": "raw",
                 "start": 2.6, "end": 4.6, "speed": 1},
                {"id": "seg-c", "sourceId": "raw",
                 "start": 1, "end": 2, "speed": 1},
            ],
            "cutDecisions": {"schemaVersion": 1, "removals": []},
        }
        return value, _write(
            os.path.join(self.producer, "edit_plan.json"), value)

    def _parent(self) -> str:
        result = os.path.join(self.producer, "final.mp4")
        ranges = (
            (120, 150, 192_000, 240_000),
            (78, 138, 124_800, 220_800),
            (30, 60, 48_000, 96_000),
        )
        filters = []
        labels = []
        for index, (first, end, sample, sample_end) in enumerate(ranges):
            filters.extend([
                f"[0:v]trim=start_frame={first}:end_frame={end},"
                f"setpts=PTS-STARTPTS[v{index}]",
                f"[0:a]atrim=start_sample={sample}:end_sample={sample_end},"
                f"asetpts=PTS-STARTPTS[a{index}]",
            ])
            labels.append(f"[v{index}][a{index}]")
        filters.append(
            "".join(labels) + "concat=n=3:v=1:a=1[v][a]")
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", self.source,
            "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-qp", "0", "-frames:v", "120",
            "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr",
            "-c:a", "pcm_s32le", "-ar", "48000", "-ac", "2", result,
        ], check=True)
        return result

    def _revision(self) -> str:
        graph_hash = publish_parent_active(self)
        graph, receipt_hash, receipt = _active_graph(
            self.producer, graph_hash)
        source_set = next(
            row for row in graph["nodes"]
            if row["nodeId"] == "node-source")["inputDigests"]["source.set"]
        manifest = json.loads(Path(self.manifest).read_text())
        source = source_rows(manifest)["raw"]
        timing = transcript(
            source, os.path.dirname(self.manifest), "raw", 48_000)
        timeline = build_projection(
            self.plan, self.plan_hash)["timelineMapHash"]
        revision = {
            "schemaVersion": 2, "parentRevisionHash": None,
            "planContentHash": plan_content_hash(self.plan),
            "planObjectHash": self.plan_hash,
            "manifestHash": self.manifest_hash,
            "sourceSnapshotSetHash": source_set,
            "transcriptTimingHash": timing["timingHash"],
            "timelineMapHash": timeline, "canvasProfileHash": "c" * 64,
            "destinationProfileHashes": ["d" * 64],
            "pictureLockHash": _PICTURE_LOCK,
            "workflowState": "PICTURE_LOCKED",
            "requestLedgerHash": "e" * 64, "renderGraphHash": graph_hash,
            "projectionReceiptHash": None,
            "authoritativeSidecars": {"compatibilityLock": _PICTURE_LOCK},
        }
        root = os.path.join(self.producer, ".sniper-authority-v1")
        _json_file(os.path.join(
            root, "objects", "plans", f"{self.plan_hash}.json"), self.plan)
        _json_file(os.path.join(
            root, "objects", "graphs", f"{graph_hash}.json"), graph)
        _json_file(os.path.join(
            root, "objects", "receipts", f"{receipt_hash}.json"), receipt)
        head = digest(revision)
        _json_file(os.path.join(
            root, "objects", "revisions", f"{head}.json"), revision)
        _json_file(os.path.join(root, "advances", "GENESIS.json"), {
            "schemaVersion": 1, "revisionHash": head,
        })
        Path(os.path.join(root, "ACTIVE_HEAD")).write_text(head + "\n")
        return head

    def _evidence(self) -> None:
        self.evidence_files = materialize_context_evidence(
            self.producer, self.source, self.parent, _TARGET)
        core = {"schemaVersion": 1, "kind": "cut-repair-acoustic-evidence",
            "parentRevisionHash": self.head, "planSha256": self.plan_hash,
            "manifestSha256": self.manifest_hash, "sourceId": "raw",
            "alignment": {
                "status": "pinned-bounded-evidence",
                "receiptSha256": self.evidence_files["alignment"]["sha256"],
                "runtimeSha256": self.evidence_files["runtime"]["sha256"],
                "modelSha256": self.evidence_files["model"]["sha256"],
                "cacheSha256": self.evidence_files["cache"]["sha256"],
            },
            "vad": {
                "status": "pinned-bounded-evidence",
                "receiptSha256": self.evidence_files["vad"]["sha256"],
            },
            "audition": {
                "status": "operator-reported-damage",
                "receiptSha256": self.evidence_files["audition"]["sha256"],
            },
            "audioIsolation": {
                "status": "dialogue-only-bounded-evidence",
                "receiptSha256": self.evidence_files["isolation"]["sha256"],
                "runtimeSha256": self.evidence_files[
                    "isolationRuntime"]["sha256"],
                "musicSfxOverlapCount": 0,
            },
            "silences": [{
                "silenceId": "silence-terminal", "segmentId": "seg-b",
                "sourceId": "raw",
                "sourceSamples": {
                    "startSample": 192_000,
                    "endSampleExclusive": 220_800,
                },
                "outputFrames": {
                    "startFrame": 72, "endFrameExclusive": 90,
                },
            }],
            "coveredPicture": [], "replaceableAudio": [],
            "replaceableAudioEvidenceHash":
                self.evidence_files["replaceableAudio"]["sha256"],
            "dependents": [],
            "parentMedia": {"path": self.parent,
                            "sha256": file_sha256(self.parent)},
            "maxDirtyFrames": 60, "maxAudioOverlapFrames": 15,
        }
        path = os.path.join(
            self.producer, "cut_repair_acoustic_evidence_v1.json")
        _write(path, {**core, "authorityHash": digest(core)})

    def _whisper_tools(self) -> tuple[str, str]:
        root = os.path.join(self.producer, "row10-qc-tools")
        os.makedirs(root)
        script = os.path.join(root, "whisper-cli")
        body = """#!/usr/bin/env python3
import json
import sys
if "--version" in sys.argv:
    print("row10-whisper-fixture-v1")
    raise SystemExit(0)
output = sys.argv[sys.argv.index("-of") + 1] + ".json"
with open(output, "w", encoding="utf-8") as stream:
    json.dump({"transcription": [{"text": "restore this phrase"}]}, stream)
"""
        Path(script).write_text(body)
        os.chmod(script, 0o700)
        model = os.path.join(root, "model.bin")
        Path(model).write_bytes(b"row10 controlled whisper model")
        return script, model


def main() -> int:
    fixture = Row10LifecycleFixture()
    print(json.dumps({
        "root": fixture.root,
        "producerDir": fixture.producer,
        "manifestPath": fixture.manifest,
        "parentRevisionHash": fixture.head,
        "parentMediaPath": fixture.parent,
        "whisperPath": fixture.whisper,
        "whisperModelPath": fixture.whisper_model,
        "contextEvidenceFiles": fixture.evidence_files,
        "contextEvidenceScope":
            "controlled-precondition-only-not-row10-qc-claim",
        "target": _TARGET,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
