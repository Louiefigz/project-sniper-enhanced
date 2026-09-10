"""Real-media analyze-to-prepare coverage for bounded picture repair."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cut_speed import render_cut_speed
from edit.compatibility_projection import build_projection
from edit.cut_repair_context_materialize import materialize
from edit.cut_repair_picture_plan_authority import PLAN_FIELD
from edit.cut_repair_prepare_media import prepare
from fingerprints import file_sha256, plan_content_hash
from ingest_admission import (
    admit_ingest_candidates,
    collect_ingest_candidates,
)
from tests._ingest_admission_fixture import runner as admission_runner
from tests._p2_repair_media_fixture import FFMPEG, FFPROBE, media


def _bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()


def _write(path: str, value: object) -> str:
    payload = _bytes(value)
    with open(path, "wb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


class _PictureFixture:
    def __init__(
        self,
        captions: bool = True,
        burned_visual: bool = False,
    ) -> None:
        self.captions = captions
        self.burned_visual = burned_visual
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.producer = os.path.join(self.root, "producer")
        self.source_dir = os.path.join(self.root, "source")
        os.makedirs(self.producer)
        os.makedirs(self.source_dir)
        _write(os.path.join(self.producer, "project.json"), {
            "intent": {"mode": "longform", "scope": "trim"},
        })
        self.source = os.path.join(self.source_dir, "raw.mov")
        self._source_media()
        self.directive = self._directive()
        self.plan, self.plan_hash = self._plan()
        self.manifest, self.manifest_hash = self._manifest()
        self.parent = self._parent()
        if self.burned_visual:
            self._burn_visual_lane()
        self.head = self._revision()
        self._evidence()
        self.context = os.path.join(self.root, "context.json")
        _write(self.context, materialize(
            self.producer, self.manifest, self.directive))
        self.staging = os.path.join(
            self.producer, ".sniper-cut-repair-staging", "picture")
        os.makedirs(self.staging)

    def _source_media(self) -> None:
        media(self.source, "30/1", True, False)

    def _directive(self) -> str:
        transcript = os.path.join(self.source_dir, "raw.transcript.json")
        _write(transcript, {"transcript": [{
            "speaker": "host",
            "words": [
                {"word": "before", "start": 0.5, "end": 0.7},
                {"word": "automation", "start": 1.9, "end": 2.1},
                {"word": "after", "start": 2.4, "end": 2.6},
            ],
        }]})
        path = os.path.join(self.root, "directive.json")
        _write(path, {
            "schemaVersion": 1, "operation": "cut.restoreSpeech",
            "mode": "analyze", "target": {"phrase": "automation"},
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
                 "start": 2, "end": 4, "speed": 1},
            ],
            "cutDecisions": {"schemaVersion": 1, "removals": []},
        }
        if self.captions:
            value["captionsTrack"] = {
                "schemaVersion": 1,
                "source": "kept-transcript",
                "defaultPolicy": "karaoke",
                "groups": [],
            }
        return value, _write(
            os.path.join(self.producer, "edit_plan.json"), value)

    def _manifest(self) -> tuple[str, str]:
        path = os.path.join(self.source_dir, "manifest.json")
        admission = admit_ingest_candidates(
            collect_ingest_candidates([Path(self.source)], None, None),
            Path(self.source_dir), admission_runner)
        admitted = admission.media_by_original[
            str(Path(self.source).absolute())]
        value = {"sources": [{
            "id": "raw", "path": admitted.snapshot_path,
            "originalPath": admitted.original_path,
            "sourceSha256": admitted.sha256,
            "admissionReceiptPath": admitted.receipt_path,
            "admissionReceiptSha256": admitted.receipt_sha256,
            "contentHash": admitted.sha256,
            "transcriptPath": "raw.transcript.json",
            "duration": 5, "fps": 30, "vfr": False,
            "resolution": [160, 90], "rotation": 0,
            "audio": {
                "present": True, "channels": 2,
                "sampleRate": 48_000,
            },
            "role": "primary",
        }], "broll": [], "music": [],
            "sourceSetAdmission": admission.binding}
        return path, _write(path, value)

    def _parent(self) -> str:
        mezzanine = os.path.join(self.producer, "parent-mezzanine.mp4")
        path = os.path.join(self.producer, "parent.mov")
        parts = os.path.join(self.root, "parent-parts")
        os.makedirs(parts)
        with open(self.manifest, encoding="utf-8") as stream:
            manifest = json.load(stream)
        render_cut_speed(self.plan, manifest, mezzanine, parts)
        audio = os.path.join(self.producer, "parent-audio.wav")
        subprocess.run([
            str(FFMPEG), "-y", "-v", "error", "-i", mezzanine,
            "-map", "0:a:0",
            "-af", "apad=whole_len=144000,atrim=end_sample=144000,"
            "asetpts=PTS-STARTPTS",
            "-c:a", "pcm_s32le", "-ar", "48000", "-ac", "2", audio,
        ], check=True)
        subprocess.run([
            str(FFMPEG), "-y", "-v", "error",
            "-i", mezzanine, "-i", audio,
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", "setpts=PTS-STARTPTS",
            "-c:v", "libx264", "-qp", "0", "-frames:v", "90",
            "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr",
            "-c:a", "pcm_s32le", "-ar", "48000", "-ac", "2", path,
        ], check=True)
        return path

    def _revision(self) -> str:
        timeline = build_projection(
            self.plan, self.plan_hash)["timelineMapHash"]
        revision = {
            "schemaVersion": 1, "workflowState": "PICTURE_LOCKED",
            "pictureLockHash": "7" * 64,
            "timelineMapHash": timeline,
            "planContentHash": plan_content_hash(self.plan),
            "manifestHash": self.manifest_hash,
        }
        head = hashlib.sha256(_bytes(revision)).hexdigest()
        root = os.path.join(self.producer, ".sniper-authority-v1")
        revisions = os.path.join(root, "objects", "revisions")
        os.makedirs(revisions)
        _write(os.path.join(revisions, f"{head}.json"), revision)
        with open(os.path.join(root, "ACTIVE_HEAD"),
                  "w", encoding="ascii") as stream:
            stream.write(head + "\n")
        return head

    def _burn_visual_lane(self) -> None:
        """Burn one unmistakable visual across the future dirty window."""
        staged = os.path.join(self.producer, "parent-visual.mov")
        subprocess.run([
            str(FFMPEG), "-y", "-v", "error", "-i", self.parent,
            "-vf", "drawbox=x=0:y=0:w=160:h=12:"
            "color=magenta:t=fill:enable='between(n,30,89)'",
            "-map", "0:v:0", "-map", "0:a:0",
            "-c:v", "libx264", "-qp", "0", "-frames:v", "90",
            "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr",
            "-c:a", "copy", staged,
        ], check=True)
        os.replace(staged, self.parent)

    def _evidence(self) -> None:
        core = {
            "schemaVersion": 1, "kind": "cut-repair-acoustic-evidence",
            "parentRevisionHash": self.head, "planSha256": self.plan_hash,
            "manifestSha256": self.manifest_hash, "sourceId": "raw",
            "alignment": {
                "status": "pinned-bounded-evidence",
                "receiptSha256": "1" * 64,
                "runtimeSha256": "2" * 64,
                "modelSha256": "3" * 64,
                "cacheSha256": "4" * 64,
            },
            "vad": {
                "status": "pinned-bounded-evidence",
                "receiptSha256": "5" * 64,
            },
            "audition": {
                "status": "operator-reported-damage",
                "receiptSha256": "6" * 64,
            },
            "audioIsolation": {
                "status": "dialogue-only-bounded-evidence",
                "receiptSha256": "9" * 64,
                "runtimeSha256": "a" * 64,
                "musicSfxOverlapCount": 0,
            },
            "silences": [{
                "silenceId": "silence-terminal",
                "segmentId": "seg-b", "sourceId": "raw",
                "sourceSamples": {
                    "startSample": 187_200, "endSampleExclusive": 192_000,
                },
                "outputFrames": {
                    "startFrame": 87, "endFrameExclusive": 90,
                },
            }],
            "coveredPicture": [],
            "replaceableAudio": [],
            "replaceableAudioEvidenceHash": "b" * 64,
            "dependents": [],
            "parentMedia": {"path": self.parent,
                            "sha256": file_sha256(self.parent)},
            "maxDirtyFrames": 60,
            "maxAudioOverlapFrames": 15,
        }
        _write(os.path.join(
            self.producer, "cut_repair_acoustic_evidence_v1.json"), {
                **core,
                "authorityHash": hashlib.sha256(_bytes(core)).hexdigest(),
            })

    def clean(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe required")
class CutRepairPicturePrepareMediaTests(unittest.TestCase):
    def test_picture_prepare_renders_and_recompiles_captions(self) -> None:
        fixture = _PictureFixture()
        try:
            value = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            operation = value["operation"]
            self.assertEqual(
                operation["method"], "extend-and-reclaim-silence")
            self.assertEqual(
                value["reviewPlan"]["cutTrack"][1]["start"], 1.9)
            self.assertEqual(
                value["reviewPlan"]["cutTrack"][1]["end"], 3.9)
            self.assertEqual(
                value["reviewPlan"]["cutTrack"][1]["generation"], 2)
            authority = value["reviewPlan"][PLAN_FIELD]
            self.assertEqual(
                authority["sourceExtension"],
                operation["sourceExtension"])
            captions = value["reviewPlan"]["dialogueCaptionAuthority"]
            self.assertEqual(
                captions["captionRevalidation"]["status"], "revalidated")
            self.assertEqual(
                value["compositeReceipt"]["output"]["videoFrames"], 90)
            self.assertTrue(
                value["compositeReceipt"]["outsideDirtyOracle"]["pcmMatches"])
        finally:
            fixture.clean()


if __name__ == "__main__":
    unittest.main(verbosity=2)
