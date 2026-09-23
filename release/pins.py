"""Build-time checks of the download pins the installer relies on.

* ``release/pins/chrome-headless-shell.json`` (written by ``release.pin_browser``
  from an actual download) must name exactly the browser build the shipped
  HyperFrames requires; its per-platform SHA-256 goes into RELEASE.json.
* ``install/requirements.lock.txt`` must carry at least one ``--hash=sha256:`` for
  every requirement, so ``pip install --require-hashes`` accepts nothing else.

Every check raises ``StagingError``; nothing is written.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from release.stage import StagingError

BROWSER_PIN = Path(__file__).resolve().parent / "pins/chrome-headless-shell.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def browser_hashes(version: str) -> dict[str, str]:
    """Per-platform SHA-256 of the pinned browser archive for ``version``."""
    try:
        pin = json.loads(BROWSER_PIN.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StagingError(f"{BROWSER_PIN.name} is missing or unreadable; run python -m release.pin_browser") from error
    if pin.get("version") != version:
        raise StagingError(f"browser pin is for {pin.get('version')}, but HyperFrames requires {version}; "
                           "run python -m release.pin_browser")
    hashes = {platform: row.get("sha256", "") for platform, row in pin.get("archives", {}).items()}
    if set(hashes) != {"mac-arm64", "mac-x64"} or not all(_SHA256.match(h) for h in hashes.values()):
        raise StagingError("browser pin must hold a SHA-256 for mac-arm64 and mac-x64")
    return dict(sorted(hashes.items()))


def check_python_lock(lock: Path) -> None:
    """Every requirement in the installer's Python lock carries a SHA-256."""
    current, missing, count = None, [], 0
    for line in lock.read_text(encoding="utf-8").splitlines() + [""]:
        text = line.strip()
        if text.startswith("--hash=sha256:"):
            current = None if _SHA256.match(text.split(":", 1)[1].rstrip(" \\")) else current
            continue
        if current is not None:
            missing.append(current)
        current = text.split("==", 1)[0] if "==" in text and not text.startswith("#") else None
        count += current is not None
    if missing or count == 0:
        raise StagingError(f"requirements.lock.txt entries without a --hash=sha256: {missing[:5] or 'no entries'}; "
                           "run python -m release.hash_lock")
