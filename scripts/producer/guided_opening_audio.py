"""Private exact PCM excerpt CLI, requiring an owned full-master completion fact.

Only the server-owned runner may provide input/event hashes captured from its
actual invocation. This command cannot authenticate arbitrary user-supplied
hashes, build a master, publish video, or grant opening/delivery approval.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from audio.program_master_excerpt import ExcerptRanges, SAMPLE_CLOCK_POLICY, extract_master_audio
from audio.program_master_selection import HeldMasterSelection, read_master_selection
from cut_preview_io import bound_json, file_hash
from palmier.process_deadline import use_process_deadline

_KEYS = {"schemaVersion", "kind", "executionInputHash", "sourceSelection", "programMasterSelection",
    "planPath", "planSha256", "manifestPath", "manifestSha256", "frameRate", "totalFrames",
    "core", "review", "sampleClockPolicy"}


@dataclass(frozen=True)
class OpeningAudioDeadline:
    """One invocation's monotonic remainder, subordinate to the owned outer clock."""

    end: float

    def remaining(self) -> float:
        """Never provide a renewed subprocess budget after the original remainder."""
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("opening audio invocation deadline exceeded")
        return remaining


def _range(value: object) -> tuple[int, int]:
    """Parse a closed half-open frame pair without boolean/integer coercion."""
    if type(value) is not dict or set(value) != {"startFrame", "endFrameExclusive"}:
        raise ValueError("opening audio frame range is malformed")
    result = value["startFrame"], value["endFrameExclusive"]
    if any(type(item) is not int for item in result):
        raise ValueError("opening audio frame endpoints must be integers")
    return result


def _selection(value: dict) -> HeldMasterSelection:
    """Match all asserted input fields to the independently held execution fact."""
    requested = value["programMasterSelection"]
    if type(requested) is not dict or type(value["sourceSelection"]) is not dict:
        raise ValueError("opening audio selection is malformed")
    event_path, event_sha = requested.get("selectionEventPath"), requested.get("selectionEventHash")
    if type(event_path) is not str:
        raise ValueError("opening audio needs an owned completion event path")
    held = read_master_selection(Path(event_path), event_sha)
    event = held.event
    expected = {"receiptPath": event["programMasterReceiptPath"],
        "receiptHash": event["programMasterReceiptHash"], "sourceBusReceiptHash": event["sourceBusReceiptHash"],
        "audioProgramInputHash": event["audioProgramInputHash"],
        "selectionEventPath": event_path, "selectionEventHash": event_sha}
    source = {key: event[key] for key in ("artifactRoot", "basePath", "sourceBusReceiptHash")}
    if requested != expected or value["sourceSelection"] != source:
        raise ValueError("opening audio selection differs from owned completion")
    for key in ("planPath", "planSha256", "manifestPath", "manifestSha256"):
        if value[key] != event[key]:
            raise ValueError("opening audio document differs from owned completion")
    bus = held.master.source_bus
    if type(value["totalFrames"]) is not int or value["totalFrames"] != bus.frames \
            or value["frameRate"] != bus.frame_rate:
        raise ValueError("opening audio clock differs from actual full-program clock")
    return held


def _input(path: Path, expected_sha: str) -> tuple[dict, ExcerptRanges]:
    """Read exact closed server-authored input; no public-file inference."""
    value = bound_json(path, expected_sha)
    if set(value) != _KEYS or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or value["kind"] != "guided-opening-audio-input" \
            or value["sampleClockPolicy"] != SAMPLE_CLOCK_POLICY:
        raise ValueError("opening audio input role or sample policy is unsupported")
    return value, ExcerptRanges(_range(value["core"]), _range(value["review"]), value["executionInputHash"])


def run(input_path: Path, output_dir: Path, authority: tuple[str, float]) -> dict:
    """Execute only within the remaining outer budget and unchanged exact input."""
    expected_sha, timeout = authority
    if not math.isfinite(timeout) or not 0 < timeout <= 7200:
        raise ValueError("opening audio requires a positive bounded remaining deadline")
    deadline = OpeningAudioDeadline(time.monotonic() + timeout)

    def guard() -> None:
        """Bind elapsed time and same input bytes across every child stage."""
        deadline.remaining()
        if file_hash(input_path) != expected_sha:
            raise RuntimeError("opening audio invocation input changed")

    with use_process_deadline(deadline):
        value, ranges = _input(input_path, expected_sha)
        held = _selection(value)
        guard()
        return extract_master_audio(held, ranges, output_dir, guard)


def main() -> int:
    """Return machine evidence only after a real completed private extraction."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    args = parser.parse_args()
    try:
        result = run(args.input, args.output, (args.input_sha256, args.timeout_seconds))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "openingApproved": False}), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
