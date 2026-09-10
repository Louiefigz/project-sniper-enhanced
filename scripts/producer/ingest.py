#!/usr/bin/env python3
"""ingest — build an ``asset_manifest.json`` for the PRODUCER pipeline.

Reads one media file, a directory of raw footage, or a project directory with
``broll/`` and/or ``music/`` sub-dirs, and emits the manifest the brain reasons
over (docs/producer/PRODUCER_PLAN.md §2.1). For each raw source it records duration, fps
(+VFR flag), resolution, rotation and audio info, content-hash-dedups repeats,
reclassifies no-audio files as b-roll, and — unless ``--no-transcribe`` — spawns
``scripts/transcribe.py`` (local Whisper; paid ASR requires explicit approval) per
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
import time
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
from local_asr_deadline import LocalAsrDeadline
from producer.headless.process_runner import ProcessRequest, run_text
from transcribe_output import parse_transcription_output
from asr_policy import (add_asr_arguments, child_asr_arguments,
                        invocation_from_options, require_paid_asr,
                        transcription_environment, use_asr_invocation)
from transcript_timing_quality import require_timing_quality
from ingest_admission import (admit_ingest_candidates, collect_ingest_candidates,
                              verify_source_set_binding)
from ingest_admitted_scan import catalog_admitted_broll, scan_admitted_music
from ingest_admitted_sources import SourceBuildContext, build_admitted_sources
from ingest_probe import (
    MEDIA_EXTS,
    status,
    warn,
)
from ingest_scan import atomic_write_json, scan_builtin_music
from transcript_source_authority import (
    bind_result,
    observe_source,
    require_same_source,
)

MANIFEST_NAME = "asset_manifest.json"
BROLL_DIRNAME = "broll"
MUSIC_DIRNAME = "music"


def fail(msg: str) -> None:
    """Emit an ``{"error": ...}`` line and exit 1 (matches sibling workers)."""
    print(json.dumps({"error": msg}), flush=True)
    sys.exit(1)


def load_deepgram_key(project_root: Path) -> Optional[str]:
    """Read only an explicitly supplied key after paid admission; never scan files."""
    del project_root  # Compatibility argument, not credential discovery authority.
    require_paid_asr()
    return os.environ.get("DEEPGRAM_API_KEY")


def _python_interpreter() -> str:
    """The project venv when present, otherwise this invoking interpreter."""
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
    source_authority: dict[str, tuple[str, int]]


def classify_inputs(input_path: Path) -> Inputs:
    """Split the input into raw sources + ``broll/``/``music/`` folders."""
    if input_path.is_file():
        return Inputs(raw_files=[input_path], broll_dir=None, music_dir=None)
    broll = input_path / BROLL_DIRNAME
    music = input_path / MUSIC_DIRNAME
    if broll.is_symlink() or music.is_symlink():
        raise RuntimeError("project broll/music ingress directories cannot be symlinks")
    raw = sorted(p for p in input_path.iterdir()
                 if p.is_file() and p.suffix.lower() in MEDIA_EXTS)
    return Inputs(
        raw_files=raw,
        broll_dir=broll if broll.is_dir() else None,
        music_dir=music if music.is_dir() else None,
    )


def _spawn_transcribe(path: Path, env: dict, interpreter: str,
                      deadline: LocalAsrDeadline | None) -> subprocess.CompletedProcess:
    """Bound the local worker and its explicitly shared child process group."""
    command = [interpreter, str(TRANSCRIBE_SCRIPT), str(path), *child_asr_arguments()]
    if deadline is None:
        return subprocess.run(command, capture_output=True, text=True, env=env)
    command.extend([
        "--local-asr-expires-at", repr(deadline.expires_at),
        "--local-asr-owned-worker",
    ])
    proc = run_text(ProcessRequest(
        command=tuple(command), stdin_text="", cwd=str(PROJECT_ROOT),
        environment=env, timeout_seconds=deadline.remaining(),
        max_output_bytes=16 * 1024 * 1024,
    ))
    deadline.guard()
    return proc


def _run_transcribe(path: Path, env: dict, interpreter: str,
                    deadline: LocalAsrDeadline | None = None) -> dict:
    """Spawn transcribe.py; return the final JSON object carrying 'transcript'."""
    if deadline is None and transcription_provider() == LOCAL_PROVIDER:
        deadline = LocalAsrDeadline.start()
    proc = _spawn_transcribe(path, env, interpreter, deadline)
    if proc.returncode != 0:
        raise RuntimeError(f"transcribe.py failed (exit {proc.returncode}): {proc.stdout[-1000:]}")
    return parse_transcription_output(proc.stdout, deadline.guard if deadline else None)


def _transcribe_source(path: Path, source_id: str, ctx: TranscribeCtx) -> Optional[str]:
    """Transcribe one source; return the relative transcript path or None.

    A failure is surfaced (warning + status) but never aborts the manifest —
    the source keeps ``transcriptPath: null`` (edge case: never silently skip).
    """
    if not ctx.enabled:
        return None
    status(status="transcribing", id=source_id, path=str(path))
    started = time.monotonic()
    try:
        deadline = (LocalAsrDeadline.start()
                    if transcription_provider() == LOCAL_PROVIDER else None)
        guard = deadline.guard if deadline else None
        env = transcription_environment()
        if ctx.key and transcription_provider() == DEEPGRAM_PROVIDER:
            require_paid_asr()
            env["DEEPGRAM_API_KEY"] = ctx.key
        authority = ctx.source_authority[str(path.absolute())]
        before = observe_source(path, authority, guard)
        result = _run_transcribe(path, env, ctx.interpreter, deadline)
        after = observe_source(path, authority, guard)
        require_same_source(before, after)
        require_timing_quality(result)
        result = bind_result(result, after)
        out_path = ctx.manifest_dir / f"{source_id}.transcript.json"
        atomic_write_json(out_path, result, guard)
    except (KeyError, OSError, RuntimeError) as exc:
        warn(f"transcription failed for {source_id}: {exc}")
        status(status="transcription_error", id=source_id, error=str(exc))
        return None
    word_count = sum(len(e.get("words", [])) for e in result.get("transcript", []))
    status(status="transcribed", id=source_id, transcriptPath=out_path.name,
           words=word_count, elapsedSeconds=round(time.monotonic() - started, 3))
    return out_path.name


def build_manifest(input_path: Path, manifest_dir: Path, no_transcribe: bool) -> dict:
    """Classify inputs, build sources + b-roll + music into the manifest dict."""
    provider = LOCAL_PROVIDER if no_transcribe else transcription_provider()
    key = load_deepgram_key(PROJECT_ROOT) if provider == DEEPGRAM_PROVIDER else None
    if not no_transcribe and provider == DEEPGRAM_PROVIDER and key is None:
        raise RuntimeError("Explicit paid Deepgram invocation requires DEEPGRAM_API_KEY")
    inputs = classify_inputs(input_path)
    candidates = collect_ingest_candidates(
        inputs.raw_files, inputs.broll_dir, inputs.music_dir)
    admission = admit_ingest_candidates(candidates, manifest_dir)
    verify_source_set_binding(
        {"sourceSetAdmission": admission.binding}, manifest_dir)
    enabled = not no_transcribe
    status(status="transcription_provider", provider=provider, enabled=enabled)
    source_authority = {
        str(Path(media.snapshot_path).absolute()):
            (media.sha256, media.size_bytes)
        for media in admission.media_by_original.values()
    }
    ctx = TranscribeCtx(
        enabled=enabled, key=key, manifest_dir=manifest_dir,
        interpreter=_python_interpreter(), source_authority=source_authority)
    source_context = SourceBuildContext(ctx, _transcribe_source)
    sources, extra_broll = build_admitted_sources(
        inputs.raw_files, source_context, admission.media_by_original)
    broll = catalog_admitted_broll(
        inputs.broll_dir, extra_broll, admission.media_by_original)
    music = scan_admitted_music(inputs.music_dir, admission.media_by_original)
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
        "sourceSetAdmission": admission.binding,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a PRODUCER asset_manifest.json")
    parser.add_argument("input_path", help="media file or directory of footage")
    parser.add_argument("--out", default=None, help="manifest output path")
    parser.add_argument("--no-transcribe", action="store_true",
                        help="skip transcription (transcriptPath: null)")
    add_asr_arguments(parser)
    args = parser.parse_args()

    input_path = Path(os.path.abspath(Path(args.input_path).expanduser()))
    if not input_path.exists():
        fail(f"input not found: {input_path}")
    if input_path.is_symlink():
        fail(f"input cannot be a symlink: {input_path}")

    base_dir = input_path if input_path.is_dir() else input_path.parent
    out_path = (Path(args.out).expanduser().resolve() if args.out
                else base_dir / MANIFEST_NAME)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with use_asr_invocation(invocation_from_options(args)):
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
