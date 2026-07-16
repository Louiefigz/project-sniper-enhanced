#!/usr/bin/env python3
"""ingest — build an ``asset_manifest.json`` for the PRODUCER pipeline.

Reads one media file, a directory of raw footage, or a project directory with
``broll/`` and/or ``music/`` sub-dirs, and emits the manifest the brain reasons
over (docs/producer/PRODUCER_PLAN.md §2.1). For each raw source it records duration, fps
(+VFR flag), resolution, rotation and audio info, content-hash-dedups repeats,
reclassifies no-audio files as b-roll, and — unless ``--no-transcribe`` — spawns
``scripts/transcribe.py`` (Deepgram by default, local Whisper when selected) per
source, saving ``<id>.transcript.json``
next to the manifest. B-roll + music cataloging live in ``ingest_scan``.

Usage:
    ingest.py <input_path> [--out manifest.json] [--no-transcribe]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve()
SCRIPTS_DIR = _HERE.parents[1]            # PROJECT_SNIPER/scripts
PROJECT_ROOT = _HERE.parents[2]           # PROJECT_SNIPER
TRANSCRIBE_SCRIPT = SCRIPTS_DIR / "transcribe.py"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from local_whisper import (DEEPGRAM_PROVIDER, LOCAL_PROVIDER,
                           transcription_provider)
from ingest_probe import (
    IMAGE_EXTS,
    MEDIA_EXTS,
    MediaProbe,
    content_hash,
    probe_media,
    status,
    warn,
)
from ingest_scan import (atomic_write_json, broll_fields, catalog_broll,
                         scan_builtin_music, scan_music)

MANIFEST_NAME = "asset_manifest.json"
BROLL_DIRNAME = "broll"
MUSIC_DIRNAME = "music"


def fail(msg: str) -> None:
    """Emit an ``{"error": ...}`` line and exit 1 (matches sibling workers)."""
    print(json.dumps({"error": msg}), flush=True)
    sys.exit(1)


def _key_from_env_file(env_path: Path) -> Optional[str]:
    """Parse one env file for DEEPGRAM_API_KEY (KEY=VALUE, no dotenv dep)."""
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):     # tolerate shell-style env files
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == "DEEPGRAM_API_KEY":
            return value.strip().strip('"').strip("'") or None
    return None


def load_deepgram_key(project_root: Path) -> Optional[str]:
    """Resolve DEEPGRAM_API_KEY: env var, then the known env files.

    Search order: process env → PROJECT_SNIPER/.env.local → .env → the
    monorepo's youtube-automation/.env (the operator keeps all API keys
    there — single source of truth, secrets never copied between repos).
    """
    key = os.environ.get("DEEPGRAM_API_KEY")
    if key:
        return key
    candidates = [
        project_root / ".env.local",
        project_root / ".env",
        project_root.parent / "youtube-automation" / ".env",
    ]
    for env_path in candidates:
        key = _key_from_env_file(env_path)
        if key:
            return key
    return None


def _python_interpreter() -> str:
    """The venv python if present (needs deepgram), else this interpreter."""
    venv = PROJECT_ROOT / ".venv" / "bin" / "python3"
    return str(venv) if venv.exists() else sys.executable


@dataclass
class Inputs:
    """Classified ingest inputs: raw source files + optional asset folders."""

    raw_files: list[Path]
    broll_dir: Optional[Path]
    music_dir: Optional[Path]


@dataclass
class TranscribeCtx:
    """Everything a per-source transcription spawn needs (keeps params ≤4)."""

    enabled: bool
    key: Optional[str]
    manifest_dir: Path
    interpreter: str


def classify_inputs(input_path: Path) -> Inputs:
    """Split the input into raw sources + ``broll/``/``music/`` folders."""
    if input_path.is_file():
        return Inputs(raw_files=[input_path], broll_dir=None, music_dir=None)
    broll = input_path / BROLL_DIRNAME
    music = input_path / MUSIC_DIRNAME
    raw = sorted(p for p in input_path.iterdir()
                 if p.is_file() and p.suffix.lower() in MEDIA_EXTS)
    return Inputs(
        raw_files=raw,
        broll_dir=broll if broll.is_dir() else None,
        music_dir=music if music.is_dir() else None,
    )


def _safe_probe(path: Path) -> Optional[MediaProbe]:
    """Probe a file, warning + returning None on ffprobe failure (corrupt file)."""
    try:
        return probe_media(str(path))
    except (RuntimeError, ValueError) as exc:
        warn(f"probe failed, skipping {path}: {exc}")
        status(status="probe_failed", path=str(path))
        return None


def _run_transcribe(path: Path, env: dict, interpreter: str) -> dict:
    """Spawn transcribe.py; return the final JSON object carrying 'transcript'."""
    proc = subprocess.run(
        [interpreter, str(TRANSCRIBE_SCRIPT), str(path)],
        capture_output=True, text=True, env=env,
    )
    result: Optional[dict] = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "error" in obj:
            raise RuntimeError(obj["error"])
        if "transcript" in obj:
            result = obj
    if result is None:
        tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
        raise RuntimeError(
            f"transcribe.py produced no transcript (exit {proc.returncode}): {tail}"
        )
    return result


def _transcribe_source(path: Path, source_id: str, ctx: TranscribeCtx) -> Optional[str]:
    """Transcribe one source; return the relative transcript path or None.

    A failure is surfaced (warning + status) but never aborts the manifest —
    the source keeps ``transcriptPath: null`` (edge case: never silently skip).
    """
    if not ctx.enabled:
        return None
    status(status="transcribing", id=source_id, path=str(path))
    env = {**os.environ}
    if ctx.key:
        env["DEEPGRAM_API_KEY"] = ctx.key
    try:
        result = _run_transcribe(path, env, ctx.interpreter)
    except RuntimeError as exc:
        warn(f"transcription failed for {source_id}: {exc}")
        status(status="transcription_error", id=source_id, error=str(exc))
        return None
    out_path = ctx.manifest_dir / f"{source_id}.transcript.json"
    atomic_write_json(out_path, result)
    word_count = sum(len(e.get("words", [])) for e in result.get("transcript", []))
    status(status="transcribed", id=source_id, transcriptPath=out_path.name, words=word_count)
    return out_path.name


def _source_entry(path: Path, source_id: str, probe: MediaProbe, chash: str) -> dict:
    """Build the manifest source record (transcriptPath filled in by caller)."""
    return {
        "id": source_id,
        "path": str(path),
        "duration": probe.duration,
        "fps": probe.fps,
        "vfr": probe.vfr,
        "resolution": [probe.width, probe.height],
        "rotation": probe.rotation,
        "audio": {
            "present": probe.audio_present,
            "channels": probe.audio_channels,
            "sampleRate": probe.audio_sample_rate,
        },
        "contentHash": chash,
        "transcriptPath": None,
        "role": "primary" if source_id == "raw-1" else "secondary",
    }


def build_sources(raw_files: list[Path], ctx: TranscribeCtx) -> tuple[list[dict], list[dict]]:
    """Probe raw files → sources, reclassifying no-audio/image files to b-roll.

    Returns ``(sources, extra_broll)``. Content-hash dedup keeps one entry per
    identical file; ids are ``raw-N`` in sorted-name order among kept sources.
    """
    sources: list[dict] = []
    extra_broll: list[dict] = []
    seen: dict[str, str] = {}                 # content_hash -> source id
    for path in raw_files:
        probe = _safe_probe(path)
        if probe is None:
            continue
        if path.suffix.lower() in IMAGE_EXTS:
            extra_broll.append(broll_fields(path, probe, category=None))
            status(status="image_reclassified_to_broll", path=str(path))
            continue
        if not probe.audio_present:
            extra_broll.append(broll_fields(path, probe, category=None))
            status(status="no_audio_reclassified_to_broll", path=str(path))
            continue
        chash = content_hash(str(path))
        if chash in seen:
            warn(f"duplicate of {seen[chash]} skipped: {path}")
            status(status="duplicate_skipped", path=str(path), duplicate_of=seen[chash])
            continue
        source_id = f"raw-{len(sources) + 1}"
        seen[chash] = source_id
        entry = _source_entry(path, source_id, probe, chash)
        entry["transcriptPath"] = _transcribe_source(path, source_id, ctx)
        sources.append(entry)
        status(status="source_added", id=source_id, duration=probe.duration, vfr=probe.vfr)
    return sources, extra_broll


def build_manifest(input_path: Path, manifest_dir: Path, no_transcribe: bool) -> dict:
    """Classify inputs, build sources + b-roll + music into the manifest dict."""
    inputs = classify_inputs(input_path)
    provider = transcription_provider()
    key = load_deepgram_key(PROJECT_ROOT) if provider == DEEPGRAM_PROVIDER else None
    enabled = not no_transcribe and (provider == LOCAL_PROVIDER or key is not None)
    status(status="transcription_provider", provider=provider, enabled=enabled)
    if not no_transcribe and provider == DEEPGRAM_PROVIDER and key is None:
        status(status="transcription_skipped", reason="deepgram_api_key_not_found")
        warn("DEEPGRAM_API_KEY not in env or .env.local — transcriptPath will be null")
    ctx = TranscribeCtx(enabled=enabled, key=key, manifest_dir=manifest_dir,
                        interpreter=_python_interpreter())
    sources, extra_broll = build_sources(inputs.raw_files, ctx)
    broll = catalog_broll(inputs.broll_dir, extra_broll)
    music = scan_music(inputs.music_dir)
    # Repo-bundled starter beds (assets/music/*) register AFTER the project's
    # own tracks so plan.music.assetId resolves out of the box (additive; ids
    # continue the music-N sequence — see ingest_scan.scan_builtin_music).
    music += scan_builtin_music(PROJECT_ROOT / "assets" / "music", music)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "sources": sources,
        "broll": broll,
        "music": music,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a PRODUCER asset_manifest.json")
    parser.add_argument("input_path", help="media file or directory of footage")
    parser.add_argument("--out", default=None, help="manifest output path")
    parser.add_argument("--no-transcribe", action="store_true",
                        help="skip transcription (transcriptPath: null)")
    args = parser.parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    if not input_path.exists():
        fail(f"input not found: {input_path}")

    base_dir = input_path if input_path.is_dir() else input_path.parent
    out_path = (Path(args.out).expanduser().resolve() if args.out
                else base_dir / MANIFEST_NAME)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        manifest = build_manifest(input_path, out_path.parent, args.no_transcribe)
    except (OSError, RuntimeError, ValueError) as exc:
        fail(str(exc))

    atomic_write_json(out_path, manifest)
    status(status="done", manifest=str(out_path),
           sources=len(manifest["sources"]),
           broll=len(manifest["broll"]),
           music=len(manifest["music"]))


if __name__ == "__main__":
    main()
