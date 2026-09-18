#!/usr/bin/env python3
"""Black / continuity safety-net for a Palmier export MP4.

The in-house render and its byte-copy MIRROR are gapless and black-free by
construction, so a Palmier export needs this ONLY when it did not come through
the verified single-clip mirror — e.g. a hand-built timeline exported from
Palmier (which bypasses the render pipeline and can leave a mid-video black
frame or a clip gap, the exact 0:47-black symptom). Reuses Audit B's glitch
detectors. Fails closed (exit 1) on any unexpected mid-video black run.

Usage: audit_export.py <export.mp4>
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audit.audit_checks import FAIL  # noqa: E402
from audit.audit_glitch import detect_black, detect_freeze  # noqa: E402


def _duration(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        raise SystemExit(f"could not probe duration of {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Palmier export black/continuity safety-net (Audit B glitch subset)")
    parser.add_argument("export", help="the exported .mp4 to audit")
    args = parser.parse_args()
    if not os.path.isfile(args.export):
        raise SystemExit(f"no such file: {args.export}")
    duration = _duration(args.export)
    results = [detect_black(args.export, duration), detect_freeze(args.export)]
    for result in results:
        print(f"{result.status.upper():4} {result.name}: {result.measured}")
    if any(result.status == FAIL for result in results):
        sys.stderr.write(
            "\nFAIL: this export has a mid-video black frame / continuity defect. "
            "Deliver a Palmier plan-push via the rendered mirror "
            "(push.py <plan> <manifest> --export), not a hand-built timeline.\n")
        return 1
    print("\nPASS: no mid-video black; export is continuity-clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
