"""Opt-in actual assemble.py graph/cache/forced-full media acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from current_render_oracle import prove
from headless.external_media_probe import POLICY_VERSION
from headless.external_media_probe_policy import MediaProbeLimits
from ingest_admission import (
    admit_ingest_candidates,
    collect_ingest_candidates,
)

SCRIPT_DIR = Path(__file__).resolve().parents[1]
GRAPH = SCRIPT_DIR / "current_render_graph_cli.py"
ASSEMBLE = SCRIPT_DIR / "assemble.py"
_LIVE = os.environ.get("RUN_LIVE_CURRENT_RENDER_GRAPH") == "1"
_EVIDENCE_ROOT = os.environ.get("CURRENT_RENDER_GRAPH_EVIDENCE_ROOT")
_DURATION = 3.0
_FRAMES = 72
_RUN_COUNTS: dict[str, int] = {}


def _media(path: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"testsrc2=s=320x180:r=24:d={_DURATION}",
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:d={_DURATION}",
        "-frames:v", str(_FRAMES), "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True)


def _admission_runner(source: str, store: str) -> dict:
    data = Path(source).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    snapshot = Path(store) / f"{digest}.media"
    snapshot.write_bytes(data)
    size = len(data)
    facts = {
        "mediaKind": "timed-media", "durationSeconds": _DURATION,
        "sizeBytes": size, "width": 320, "height": 180,
        "videoStreams": 1, "audioStreams": 1, "streamCount": 2,
        "declaredFrames": _FRAMES,
    }
    return {
        "schemaVersion": 1, "policy": POLICY_VERSION,
        "snapshot": {"path": str(snapshot), "sha256": digest,
                     "sizeBytes": size},
        "limits": vars(MediaProbeLimits()),
        "image": {"imageId": f"sha256:{'a' * 64}"},
        "isolation": {"networkMode": "none"},
        "network": {"schemaVersion": 1},
        "decoded": {
            "schemaVersion": 1, "ok": True, "decoded": True, "facts": facts,
        },
    }


def _plan(card_text: str | None = None) -> dict:
    graphics = [] if card_text is None else [{
        "kind": "statement-card", "outStart": 0.0, "outEnd": _DURATION,
        "anchor": "own-screen", "reason": "dirty-scene graph acceptance",
        "spec": {"variant": "classic", "text": card_text, "bg": "dark"},
    }]
    return {
        "planVersion": 2,
        "target": {"mode": "longform", "scope": "trim",
                   "durationTargetS": _DURATION},
        "cutTrack": [{
            "sourceId": "raw-1", "start": 0.0,
            "end": _DURATION, "speed": 1.0,
        }],
        "reframe": {"strategy": "none"}, "titleCards": [],
        "graphicsTrack": graphics, "punchIns": [], "brollTrack": [],
        "transitions": [], "captions": {"burn": False, "style": "karaoke"},
        "music": {"enabled": False}, "chapters": None,
    }


def _manifest(root: Path, source: Path) -> Path:
    admission = admit_ingest_candidates(
        collect_ingest_candidates([source], None, None), root,
        _admission_runner)
    media = admission.media_by_original[str(source.absolute())]
    row = {
        "id": "raw-1", "path": media.snapshot_path,
        "originalPath": media.original_path,
        "sourceSha256": media.sha256,
        "admissionReceiptPath": media.receipt_path,
        "admissionReceiptSha256": media.receipt_sha256,
        "duration": _DURATION, "fps": 24.0, "vfr": False,
        "resolution": [320, 180], "rotation": 0,
        "audio": {"present": True, "channels": 1, "sampleRate": 48000},
        "contentHash": media.sha256, "transcriptPath": None, "role": "primary",
    }
    path = root / "asset_manifest.json"
    path.write_text(json.dumps({
        "sources": [row], "broll": [], "music": [],
        "sourceSetAdmission": admission.binding,
    }))
    return path


def _project(
    root: Path, base: Path, card_text: str | None = None,
) -> tuple[Path, Path]:
    root.mkdir()
    shutil.copyfile(base, root / "base_final.mp4")
    (root / "edit_plan.json").write_text(json.dumps(_plan(card_text)))
    (root / "timeline_map.json").write_text(json.dumps({
        "segments": [], "outputDuration": _DURATION,
    }))
    return root / "edit_plan.json", root / "final.mp4"


def _command(
    producer: Path,
    plan: Path,
    manifest: Path,
    output: Path,
) -> list[str]:
    cache = producer / "scene-cache"
    cache.mkdir(exist_ok=True)
    renderer = [
        str(ASSEMBLE), str(producer / "base_final.mp4"), str(plan),
        str(output), "--manifest", str(manifest),
        "--require-source-set-admission", "--cache-dir", str(cache),
    ]
    command = [
        sys.executable, str(GRAPH), "--phase", "assemble",
        "--producer-dir", str(producer), "--plan", str(plan),
        "--manifest", str(manifest), "--base", str(producer / "base_final.mp4"),
        "--output", str(output), "--cache-dir", str(cache),
    ]
    return [*command, "--", *renderer]


def _base_command(
    producer: Path,
    plan: Path,
    manifest: Path,
    source: Path,
) -> list[str]:
    staged = producer / "final.mp4"
    child = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-c", "copy", str(staged),
    ]
    return [
        sys.executable, str(GRAPH), "--phase", "base",
        "--producer-dir", str(producer), "--plan", str(plan),
        "--next-plan", str(plan), "--manifest", str(manifest),
        "--base", str(producer / "base_final.mp4"),
        "--output", str(staged), "--", *child,
    ]


def _run(command: list[str]) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, cwd=SCRIPT_DIR)
    producer = Path(command[command.index("--producer-dir") + 1])
    phase = command[command.index("--phase") + 1]
    key = str(producer)
    _RUN_COUNTS[key] = _RUN_COUNTS.get(key, 0) + 1
    events = producer / "acceptance-events"
    events.mkdir(exist_ok=True)
    stem = f"{_RUN_COUNTS[key]:02d}-{phase}"
    (events / f"{stem}.stdout.ndjson").write_text(result.stdout)
    (events / f"{stem}.stderr.log").write_text(result.stderr)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-12000:])
    return result.stdout


def _forced(command: list[str]) -> list[str]:
    command.insert(command.index("--"), "--force-full")
    return command


def _active_receipt(producer: Path) -> dict:
    root = producer / ".render-graph-v1"
    pointer = json.loads((root / "ACTIVE.json").read_text())
    return json.loads((
        root / "generations" / pointer["graphHash"] / "receipts"
        / f"{pointer['receiptHash']}.json").read_text())


def _active_graph(producer: Path) -> dict:
    root = producer / ".render-graph-v1"
    pointer = json.loads((root / "ACTIVE.json").read_text())
    return json.loads((
        root / "generations" / pointer["graphHash"] / "graph.json").read_text())


@contextmanager
def _workspace(name: str) -> Iterator[Path]:
    if _EVIDENCE_ROOT:
        root = Path(_EVIDENCE_ROOT).resolve() / name
        root.mkdir(parents=True, exist_ok=False)
        yield root
        return
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp).resolve()


@unittest.skipUnless(_LIVE, "set RUN_LIVE_CURRENT_RENDER_GRAPH=1")
class LiveCurrentRenderGraphAcceptance(unittest.TestCase):
    def test_actual_assemble_cache_hit_matches_isolated_forced_full(self) -> None:
        with _workspace("warm-cache-versus-forced") as root:
            source = root / "source.mp4"
            _media(source)
            (root / "project.json").write_text(json.dumps({
                "origin": "fixture", "history": [],
                "resolvedIntent": {
                    "mode": "longform", "scope": "trim", "lanes": {},
                },
            }))
            manifest = _manifest(root / "source-authority", source)
            incremental = root / "incremental"
            forced = root / "forced"
            incremental_plan, incremental_final = _project(incremental, source)
            forced_plan, forced_final = _project(forced, source)
            handoff = _run(_base_command(
                incremental, incremental_plan, manifest, source))
            self.assertIn("render_graph_base_handoff", handoff)
            incremental_final.replace(incremental / "base_final.mp4")
            first = _run(_command(
                incremental, incremental_plan, manifest,
                incremental_final))
            self.assertIn("render_graph_committed", first)
            warm = _run(_command(
                incremental, incremental_plan, manifest,
                incremental_final))
            self.assertIn("render_graph_cache_hit", warm)
            control = _run(_forced(_command(
                forced, forced_plan, manifest, forced_final)))
            self.assertIn("render_graph_committed", control)
            receipt = _active_receipt(forced)
            self.assertEqual(receipt["executionMode"], "forced-full")
            oracle = prove(
                incremental_final, forced_final, root / "oracle.json")
            self.assertTrue(oracle["passed"])

    def test_dirty_scene_matches_independent_forced_full(self) -> None:
        with _workspace("dirty-scene-versus-forced") as root:
            source = root / "source.mp4"
            _media(source)
            (root / "project.json").write_text(json.dumps({
                "origin": "fixture", "history": [],
                "resolvedIntent": {
                    "mode": "longform", "scope": "trim", "lanes": {},
                },
            }))
            manifest = _manifest(root / "source-authority", source)
            incremental = root / "incremental"
            forced = root / "forced"
            plan, final = _project(incremental, source, "BEFORE")
            _run(_command(incremental, plan, manifest, final))
            prior_graph = _active_graph(incremental)
            plan.write_text(json.dumps(_plan("AFTER")))
            changed = _run(_command(incremental, plan, manifest, final))
            self.assertIn('"status": "rendered"', changed)
            receipt = _active_receipt(incremental)
            current_graph = _active_graph(incremental)
            expected = {
                "node-scene-0000", "node-composite", "node-final"}
            self.assertTrue(expected.issubset(set(receipt["dirtyNodeIds"])))
            if prior_graph["toolchainHash"] == current_graph["toolchainHash"]:
                self.assertEqual(receipt["dirtyNodeIds"], [
                    "node-scene-0000", "node-composite", "node-final"])
            control_plan, control_final = _project(forced, source, "AFTER")
            _run(_forced(_command(
                forced, control_plan, manifest, control_final)))
            oracle = prove(final, control_final, root / "dirty-oracle.json")
            self.assertTrue(oracle["passed"])
            self.assertTrue(oracle["decodedAudioMatch"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
