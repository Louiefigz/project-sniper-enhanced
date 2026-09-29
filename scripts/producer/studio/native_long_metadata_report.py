"""Read-only size report for ONE Long attempt folder (P4-25 item 2, M-145; the real runs are P4-30 and P4-32).

It sizes, by ``lstat`` only, the files the shared JSON reader must admit: ``export-request.json``, every owner
receipt (``*.render.json``) and every StageEvidence file (``*-stage.json``), at any depth below the attempt.
It never opens, hashes or writes a file and never follows a link: a linked file or folder is counted under
``links`` and is not sized. A folder it cannot list stops the report (exit 2) instead of being skipped.
No limit is raised and no field is omitted (P4-25 item 3): ``limitBytes`` is ``cut_preview_io.MAX_JSON``,
unchanged, and ``stop`` is the plan's condition, the largest sized file above 80 % of that limit.

    native_long_metadata_report.py <attempt folder>   prints one JSON object; exit 0, or 2 on a bad argument
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import MAX_JSON  # noqa: E402  (after the run-by-path prepend)

CLASSES = ('exportRequest', 'ownerReceipt', 'stageEvidence')
STOP_ABOVE_BYTES = MAX_JSON * 4 // 5  # the largest size at or below 80 % of the limit
TOP = 10


def file_class(name: str) -> str | None:
    """The P4-25 class a file name belongs to, or None for every other file."""
    if name == 'export-request.json':
        return 'exportRequest'
    if name.endswith('.render.json'):
        return 'ownerReceipt'
    return 'stageEvidence' if name.endswith('-stage.json') else None


def _refuse_unlistable(error: OSError) -> None:
    """os.walk skips a folder it cannot list unless told otherwise; a skipped folder would under-report."""
    raise error


def entries(attempt: Path) -> list[Path]:
    """Every name below the attempt; linked folders are listed as names but never entered."""
    found: list[Path] = []
    for folder, directories, files in os.walk(attempt, onerror=_refuse_unlistable):
        found += [Path(folder, name) for name in directories + files]
    return found


def measure(attempt: Path) -> tuple[list[dict], int]:
    """Rows ``{path, class, bytes}`` for matching regular files, plus the number of links seen."""
    rows, links = [], 0
    for path in entries(attempt):
        info = path.lstat()
        links += stat.S_ISLNK(info.st_mode)
        category = file_class(path.name)
        if category and stat.S_ISREG(info.st_mode):
            rows.append({'path': str(path.relative_to(attempt)), 'class': category, 'bytes': info.st_size})
    return rows, links


def report(attempt: Path) -> dict:
    """The sizes P4-25 lists: per-class counts and maxima, the ten largest ``{path: bytes}``, the maximum."""
    if attempt.is_symlink() or not attempt.is_dir():
        raise ValueError(f'the metadata report needs a real attempt folder, not {attempt}')
    rows, links = measure(attempt)
    rows.sort(key=lambda row: (-row['bytes'], row['path']))
    largest = rows[0] if rows else None
    return {'schemaVersion': 1, 'attempt': str(attempt.absolute()), 'limitBytes': MAX_JSON,
            'stopAboveBytes': STOP_ABOVE_BYTES, 'links': links,
            'counts': {name: sum(row['class'] == name for row in rows) for name in CLASSES},
            'maximumByClass': {name: max((row['bytes'] for row in rows if row['class'] == name), default=None)
                               for name in CLASSES},
            'top10': {row['path']: row['bytes'] for row in rows[:TOP]},
            'maximum': largest and {'path': largest['path'], 'bytes': largest['bytes'],
                                    'fractionOfLimit': round(largest['bytes'] / MAX_JSON, 6)},
            'stop': largest is not None and largest['bytes'] > STOP_ABOVE_BYTES}


def main(argv: list[str] | None = None) -> int:
    """One attempt folder in, one JSON object out; exit 2 on a usage error or an unreadable folder."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print('usage: native_long_metadata_report.py <attempt folder>', file=sys.stderr)
        return 2
    try:
        value = report(Path(args[0]))
    except (OSError, ValueError) as error:
        print(json.dumps({'error': str(error)}))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
