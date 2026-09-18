#!/usr/bin/env python3
"""Create a word-timed study transcript with the local whisper.cpp runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, os.path.join(_SCRIPTS, "producer"))

from local_whisper import (  # noqa: E402
    LocalTranscribeRequest,
    transcribe_media,
)
from local_asr_cli import add_local_asr_arguments, emit_local_result, local_cli_context  # noqa: E402
from local_asr_deadline import LocalAsrDeadline, use_local_asr_deadline  # noqa: E402
from producer.ingest_scan import atomic_write_json  # noqa: E402
from producer.study.study_transcribe import study_deadline  # noqa: E402


def emit(status: str, **fields) -> None:
    """Write one NDJSON status line."""
    print(json.dumps({"status": status, **fields}), flush=True)


def write_transcript(video: str, output: str, deadline: LocalAsrDeadline | None = None) -> dict:
    """Transcribe ``video`` locally and atomically persist the shared payload."""
    with use_local_asr_deadline(study_deadline(deadline)) as held:
        result = transcribe_media(LocalTranscribeRequest(path=video),
            emit=lambda event: print(json.dumps(event), flush=True), deadline=held)
        held.guard()
        destination = Path(os.path.abspath(output))
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(destination, result, guard=held.guard)
        words = sum(len(row.get("words") or []) for row in result.get("transcript") or [])
        emit_local_result({"status": "done", "transcriptPath": str(destination), "words": words,
                           "model": result.get("model")}, held)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Local word transcript for a reference", allow_abbrev=False)
    parser.add_argument("video")
    parser.add_argument("output")
    add_local_asr_arguments(parser)
    args = parser.parse_args()
    try:
        with local_cli_context(args) as deadline:
            write_transcript(args.video, args.output, deadline)
    except (RuntimeError, OSError, ValueError) as exc:
        emit("error", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
