#!/usr/bin/env python3
"""Private child entry point for one sealed graphics render."""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    os.umask(0o077)
    try:
        request = json.load(sys.stdin)
        keys = {"attemptId", "attemptRoot", "buildDigest", "cacheDir",
                "requestDigest", "sealPath", "sealSha256", "selectionId"}
        if not isinstance(request, dict) or set(request) != keys:
            raise RuntimeError("render worker request schema is invalid")
        if not all(isinstance(request[key], str) for key in keys):
            raise RuntimeError("render worker request values must be strings")
        from headless.overlay_seal import OverlaySealBinding, load_overlay
        from headless.overlay_seal_store import OverlaySealLocator
        from graphics.sealed_graphics_render import render_presealed
        locator = OverlaySealLocator(request["sealPath"], request["sealSha256"])
        binding = OverlaySealBinding(
            request["attemptRoot"], request["attemptId"],
            request["requestDigest"], request["buildDigest"],
            request["selectionId"])
        result = render_presealed(load_overlay(locator, binding), request["cacheDir"])
        sys.stdout.write(json.dumps(
            result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
        return 0
    except Exception as exc:
        sys.stderr.write(f"render worker error: {type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
