"""Reuse Producer's verbatim phrase grouper for native DOM caption placement.

This adapter does no ASR, rendering, correction, suppression or quality approval.
It returns occurrence IDs only; the controller retains the exact word/frame data.
"""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from captions.captions_whisper import _whisper_cues
from producer_config import CAPTIONS


def _words(value: object) -> tuple[list[dict], Fraction]:
    """Validate the bounded occurrence clock before sharing the phrase kernel."""
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError("Native caption input requires direction schema1")
    rate = Fraction(value["frameRate"])
    if rate <= 0:
        raise ValueError("Native caption frame rate must be positive")
    rows = value.get("occurrences")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 30000:
        raise ValueError("Native caption occurrences are missing or unbounded")
    words = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 7 or row[0] != index \
                or any(type(row[key]) is not int for key in (0, 1, 2, 3, 4, 6)) \
                or not 0 <= row[3] < row[4] <= value["totalFrames"] \
                or not isinstance(row[5], str) or not row[5]:
            raise ValueError("Native caption occurrence is malformed")
        words.append(dict(occurrence=index, segment=row[1], word=row[5],
                          start=float(Fraction(row[3]) / rate),
                          end=float(Fraction(row[4]) / rate)))
    return words, rate


def native_groups(value: object) -> list[list[int]]:
    """Apply the existing gap/word/sentence policy without joining source cuts."""
    words, _rate = _words(value)
    runs: list[list[dict]] = []
    for word in words:
        if not runs or runs[-1][-1]["segment"] != word["segment"]:
            runs.append([word])
        else:
            runs[-1].append(word)
    return [[word["occurrence"] for word in group]
            for run in runs for group in _whisper_cues(run, CAPTIONS["WHISPER"])]


def main() -> None:
    """Read one controller-owned file and emit compact occurrence groups."""
    source = Path(sys.argv[1])
    if source.is_symlink() or source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Native caption input is linked or oversized")
    value = json.loads(source.read_text(encoding="utf-8"))
    print(json.dumps(dict(schemaVersion=1, groups=native_groups(value))))


if __name__ == "__main__":
    main()
