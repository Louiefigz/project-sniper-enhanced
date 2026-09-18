"""Every reference the deep study decodes is an admitted snapshot.

The GUI admits a reference before studying it; the agent skill path used to run
``study_deep.py`` straight on a downloaded or local file. ``admitted_study_input``
closes that gap: an input that is already an admitted reference snapshot
(``<sha256>.media`` with its retained receipt beside it) is studied as is;
anything else is first fully decoded in the native admission jail
(headless/admit_external_media_cli.admit_reference) and the study then reads only
the immutable admitted snapshot.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from headless.admit_external_media_cli import RECEIPT_DIR, admit_reference
from ingest_admission_contract import receipt_snapshot

_SNAPSHOT = re.compile(r"[0-9a-f]{64}\.media")
STORE_NAME = "reference-admission"


def _admitted(path: Path) -> bool:
    """Whether ``path`` is a snapshot bound by a valid retained receipt beside it."""
    receipts = path.parent / RECEIPT_DIR
    if not _SNAPSHOT.fullmatch(path.name) or not receipts.is_dir() or receipts.is_symlink():
        return False
    for receipt_file in sorted(receipts.glob("*.json")):
        try:
            receipt = json.loads(receipt_file.read_bytes()[:4 * 1024 * 1024])
            if receipt.get("snapshot", {}).get("path") == str(path):
                receipt_snapshot(receipt, path.parent)
                return True
        except (OSError, ValueError, RuntimeError, AttributeError):
            continue
    return False


def admitted_study_input(video: str, out_dir: str) -> str:
    """Path of the admitted snapshot to study, admitting ``video`` first when needed."""
    path = Path(os.path.abspath(video))
    if _admitted(path):
        return str(path)
    authority = admit_reference(str(path), str(Path(os.path.abspath(out_dir)) / STORE_NAME))
    return authority["snapshotPath"]
