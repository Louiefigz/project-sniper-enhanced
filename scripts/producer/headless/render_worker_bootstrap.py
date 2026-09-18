#!/usr/bin/env python3
"""Isolated stdlib bootstrap for the sealed render worker package."""
from __future__ import annotations

import os
import runpy
import sys


def main() -> int:
    """Add exactly the checked producer root after isolated startup."""
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode:
        raise RuntimeError("render worker Python startup is not isolated")
    producer = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, producer)
    runpy.run_module("headless.render_worker", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
