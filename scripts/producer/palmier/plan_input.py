"""Read saved or in-memory edit plans for the Palmier preflight."""
from __future__ import annotations

import json
import sys

from palmier.mcp_client import PalmierError


def read_plan(path: str, from_stdin: bool) -> dict:
    """Return one plan object without ever persisting an editor snapshot."""
    try:
        with sys.stdin if from_stdin else open(path) as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        source = "stdin" if from_stdin else path
        raise PalmierError(f"cannot read edit plan {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("edit plan is not a JSON object")
    return value
