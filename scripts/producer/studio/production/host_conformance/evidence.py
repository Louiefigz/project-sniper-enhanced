"""Evidence records for conformance probes: bounded, path-neutral JSON.

Machine paths are replaced with neutral tokens before anything is written, so a
record can sit in shipped docs without naming a home directory or scratch root.
Credential values are never read by the probes, so there is nothing to redact
beyond paths; this module still refuses to serialize the environment.
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MAX_TEXT = 600


@dataclass(frozen=True)
class Neutral:
    """Path prefixes to neutralize, longest first."""

    scratch: Path

    def text(self, value: str) -> str:
        """Replace machine-specific prefixes (and the host's slug of the scratch path)."""
        resolved = str(self.scratch.resolve())
        slug = "".join(ch if ch.isalnum() else "-" for ch in resolved)
        out = value.replace(resolved, "<scratch>").replace(slug, "<scratch-slug>")
        out = out.replace(str(self.scratch), "<scratch>")
        temp = tempfile.gettempdir()
        out = out.replace(str(Path(temp).resolve()), "<tmpdir>").replace(temp, "<tmpdir>")
        out = out.replace(str(Path.home()), "~")
        return out if len(out) <= MAX_TEXT else out[:MAX_TEXT] + "…"

    def value(self, value: object) -> object:
        """Recursively neutralize strings inside JSON-like data."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {str(k): self.value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(v) for v in value]
        return value


def pick(event: dict | None, *keys: str) -> dict | None:
    """Selected top-level fields of an event, or None when the event is absent."""
    if event is None:
        return None
    return {key: event.get(key) for key in keys if key in event}


def write(path: Path, record: dict, neutral: Neutral) -> Path:
    """Write one scenario record with its capture time."""
    if "env" in record:
        raise ValueError("Evidence records never carry a process environment")
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}
    path.write_text(json.dumps(neutral.value(stamped), indent=2, sort_keys=False) + "\n")
    return path
