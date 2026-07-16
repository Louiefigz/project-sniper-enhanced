#!/usr/bin/env python3
"""Create a word-timed study transcript with the local whisper.cpp runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _SCRIPTS)

from local_whisper import (  # noqa: E402
    LocalTranscribeRequest,
    LocalWhisperError,
    transcribe_media,
)


def emit(status: str, **fields) -> None:
    """Write one NDJSON status line."""
    print(json.dumps({"status": status, **fields}), flush=True)


def write_transcript(video: str, output: str) -> dict:
    """Transcribe ``video`` locally and atomically persist the shared payload."""
    result = transcribe_media(
        LocalTranscribeRequest(path=video),
        emit=lambda event: print(json.dumps(event), flush=True),
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    temp = output + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    os.replace(temp, output)
    words = sum(len(row.get("words") or []) for row in result.get("transcript") or [])
    emit("done", transcriptPath=os.path.abspath(output), words=words,
         model=result.get("model"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Local word transcript for a reference")
    parser.add_argument("video")
    parser.add_argument("output")
    args = parser.parse_args()
    if not os.path.isfile(args.video):
        emit("error", error=f"not a file: {args.video}")
        return 1
    try:
        write_transcript(args.video, args.output)
    except (LocalWhisperError, OSError, ValueError) as exc:
        emit("error", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
