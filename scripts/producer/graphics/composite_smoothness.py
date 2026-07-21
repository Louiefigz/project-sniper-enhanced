"""YDIF duplicate-frame gate shared by legacy and prebound compositors."""

from __future__ import annotations

import os

YDIF_DUP_FAIL = 0.08


def duplicate_ratio(
    lines: list[str], exempt: list[tuple[int, int]] | None = None
) -> float:
    """Return exact-duplicate ratio outside intentional full-frame holds."""
    spans = exempt or []
    counted = [
        line
        for index, line in enumerate(lines)
        if not any(start <= index < end for start, end in spans)
    ]
    if not counted:
        return 0.0
    duplicates = sum(
        line.rsplit("YDIF=", 1)[1].strip() in {"0", "0.0", "0.000000"}
        for line in counted
    )
    return duplicates / len(counted)


def read_inline_ydif(path: str, exempt: list[tuple[int, int]] | None = None) -> float:
    """Consume a composite pass's signalstats dump, failing on absent proof."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [line for line in handle if "YDIF=" in line]
    except OSError as exc:
        raise RuntimeError(
            f"inline YDIF dump unreadable ({exc}); smoothness is unknown"
        ) from exc
    if not lines:
        raise RuntimeError("inline YDIF dump has no YDIF observations")
    os.remove(path)
    return duplicate_ratio(lines, exempt)
