"""Small shared helpers for the FRAME.IO REVIEW pipeline.

``log`` mirrors the rest of the repo's Python workers: a ``[SNIPER:frameio]``
trace to **stderr**, gated by SNIPER_DEBUG (on unless set to "0"). stdout is
reserved for NDJSON events in --server mode, so debug never pollutes it.
"""

from __future__ import annotations

import os
import sys

_DEBUG = os.environ.get("SNIPER_DEBUG", "1") != "0"


def log(scope: str, msg: str) -> None:
    if _DEBUG:
        print(f"[SNIPER:frameio:{scope}] {msg}", file=sys.stderr, flush=True)
