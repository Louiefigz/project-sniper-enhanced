"""Create an isolated, explicitly synthetic Studio UI fixture, never a master.

Usage: .venv/bin/python scripts/producer/tests/fixtures/create_studio_ui_fixture.py WORKSPACE
The project must not exist. No critic, approval, or delivery receipt is created.
The base contains the opening hook card rendered by the existing overlay lane.
The source is a color plate plus tone, not dialogue; its transcript is empty.
Plan validity is checked with the real template/matrix/transcript gates, but
is not evidence of perceptual quality or production throughput.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fingerprints import file_sha256, fingerprint_record
from fingerprint_io import write_json_atomic
from base_reuse import observe_inputs, seal_binding
from graphics.template_contract import validate_entry
from graphics_planner import output_words
from plan_lint import lint

_DURATION = 18
_CANVAS = [1080, 1920]
_DATE = "2026-09-06T00:00:00Z"
_PRODUCER_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, value: object) -> None:
    """Create a new fixture document without replacing an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)


def _plan() -> dict:
    """A legal short/light plan with independent timing and copy targets."""
    return {
        "planVersion": 1, "target": {"mode": "short", "scope": "light",
            "durationTargetS": _DURATION, "graphicsStyle": "overlay-rich"},
        "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": _DURATION, "speed": 1}],
        "reframe": {"strategy": "center"}, "captions": {"burn": False},
        "music": {"enabled": False}, "brollTrack": [],
        "titleCards": [{"style": "hook", "text": "Studio review",
                        "outStart": 0, "outEnd": 1}],
        "graphicsTrack": [
            {"id": "g-00000001", "kind": "text-element", "outStart": 1, "outEnd": 3.5,
             "anchor": "free-band", "reason": "synthetic timing-control test",
             "spec": {"text": "Review the system", "fontSize": 64}},
            {"id": "g-00000002", "kind": "icon-badge", "outStart": 6, "outEnd": 9,
             "anchor": "free-band", "reason": "synthetic pinned-icon preview",
             "spec": {"icon1": "youtube", "icon2": "", "icon3": "", "icon4": "",
                      "at1": 0.2, "label": ""}},
            {"id": "g-00000003", "kind": "hw-callout-circle", "outStart": 12,
             "outEnd": _DURATION, "anchor": "free-band",
             "reason": "synthetic supported label-copy test ending with output",
             "spec": {"x": 240, "y": 780, "w": 600, "h": 300, "label": "Review",
                      "labelAt": "below", "scribble": False, "seed": 4,
                      "drawAt": 0.2, "accent": "#FFFFFF"}},
        ],
    }


def _register(workspace: Path, producer: Path) -> None:
    """Append a new fixture without removing earlier registry entries."""
    registry = workspace / ".project-sniper" / "projects.json"
    entries = json.loads(registry.read_text()) if registry.exists() else []
    if not isinstance(entries, list):
        raise ValueError("fixture workspace registry must be an array")
    entries.append({"dir": str(producer), "title": f"SYNTHETIC · {producer.parent.name}",
                    "updatedAt": _DATE})
    registry.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(str(registry), entries, indent=2)


def _source_media(media: Path) -> None:
    """Create only bounded synthetic portrait footage and a quiet test tone."""
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        f"color=c=0x336699:s=1080x1920:d={_DURATION}:r=30", "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={_DURATION}",
        "-af", "volume=0.08",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest", str(media),
    ], check=True, capture_output=True, timeout=30)


def _manifest(source: Path) -> dict:
    """Bind exact source bytes and an explicitly empty non-dialogue transcript."""
    media = source / "raw-1.mp4"
    transcript = source / "raw-1.transcript.json"
    _write(transcript, {"words": [], "transcript": [], "syntheticTestOnly": True,
                       "note": "Generated color plate and 440 Hz tone; no speech."})
    return {"generatedAt": _DATE, "input": str(source),
                "sources": [{"id": "raw-1", "path": str(media), "duration": _DURATION, "fps": 30,
                             "vfr": False, "resolution": _CANVAS, "rotation": 0,
                             "audio": {"present": True, "channels": 2, "sampleRate": 48000},
                             "contentHash": file_sha256(str(media)),
                             "transcriptPath": str(transcript), "role": "a-roll"}],
                "broll": [], "music": []}


def validate_fixture_plan(plan: dict, manifest: dict, producer: Path) -> list[str]:
    """Require real template/matrix gates, including loaded output-time words."""
    for entry in plan["graphicsTrack"]:
        validate_entry(entry)
    words = output_words(plan, str(producer), manifest)
    report = lint(plan, manifest, words)
    if report.errors:
        raise ValueError("synthetic fixture plan is invalid: " + "; ".join(report.errors))
    return report.warnings


def _base_media(source: Path, producer: Path, plan: dict) -> None:
    """Bake the declared hook through the real overlay lane, never a final."""
    cards = producer / "synthetic_title_cards.json"
    _write(cards, plan["titleCards"])
    subprocess.run([
        sys.executable, str(_PRODUCER_ROOT / "captions" / "overlays.py"),
        str(source / "raw-1.mp4"), str(cards), str(producer / "base_final.mp4"),
    ], check=True, capture_output=True, timeout=45)


def _project_documents(producer: Path, plan: dict, manifest: dict, inputs: dict) -> None:
    """Write initial draft metadata only after the declared base exists."""
    _write(producer / "edit_plan.json", plan)
    _write(producer / "base_plan.json", plan)
    receipt = {**fingerprint_record(plan),
               "manifestPath": str(producer / "asset_manifest.json"),
               "baseReuse": seal_binding(str(producer / "base_final.mp4"),
                                         plan, inputs, "legacy-v1")}
    _write(producer / "base.fingerprint.json", receipt)
    _write(producer / "asset_manifest.json", manifest)
    _write(producer.parent / "source" / "asset_manifest.json", manifest)
    _write(producer.parent / "project.json", {
        "origin": "raw", "history": [], "syntheticTestOnly": True,
        "intent": {"mode": "short", "scope": "light", "lanes": {}, "music": False}})


def create(workspace: Path, name: str = "studio-ui-synthetic") -> dict:
    """Generate disposable media and a valid, explicitly non-deliverable plan."""
    if not re.fullmatch(r"studio-ui-synthetic(?:-\d+)?", name):
        raise ValueError("use an isolated studio-ui-synthetic fixture name")
    project = workspace.resolve() / name
    project.mkdir(parents=True, exist_ok=False)
    source, producer = project / "source", project / "producer"
    source.mkdir()
    producer.mkdir()
    started = time.monotonic()
    _source_media(source / "raw-1.mp4")
    plan, manifest = _plan(), _manifest(source)
    warnings = validate_fixture_plan(plan, manifest, producer)
    inputs = observe_inputs(manifest)
    _base_media(source, producer, plan)
    if observe_inputs(manifest) != inputs:
        raise RuntimeError("synthetic source changed while rendering its base")
    _project_documents(producer, plan, manifest, inputs)
    _register(workspace, producer)
    return {"project": str(project), "producerDir": str(producer),
            "syntheticTestOnly": True, "planErrors": [], "planWarnings": warnings,
            "fixtureSetupMs": round((time.monotonic() - started) * 1000)}


if __name__ == "__main__":
    print(json.dumps(create(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "studio-ui-synthetic")))
