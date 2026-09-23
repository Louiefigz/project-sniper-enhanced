#!/usr/bin/env python3
"""Write a support bundle that is private by construction.

    install/diagnostics.command

The bundle is built from structured facts: release identity, machine and tool
versions, the doctor's report, install receipts (versions and hashes) and the
installer's own step log. It copies no footage, transcript, edit plan, key or
conversation (your conversation with your agent stays in your agent).

Paths are written relative to your home folder, and any other /Users/<name> is
masked, so your account name does not travel with the bundle.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
RUNTIME = PKG / "runtime"



def _run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def machine() -> dict:
    """Versions only; no hostnames, serials or user names. Node is the one this install uses."""
    node = os.environ.get("SNIPER_NODE_PATH") or "node"
    return {"macos": platform.mac_ver()[0], "arch": platform.machine(),
            "node": _run([node, "--version"]), "python": platform.python_version()}


def receipts() -> dict:
    """Each step's receipt (what it was built from); the per-file records are left out."""
    folder = RUNTIME / "state" / "receipts"
    return {p.name: p.read_text(encoding="utf-8")[:200] for p in sorted(folder.glob("*"))
            if p.is_file() and not p.name.endswith(".tree.json")} if folder.exists() else {}


def mask_home(text: str) -> str:
    """Replace this account's home folder, then any other account's, in serialized output."""
    return re.sub(r"/Users/[^/\s\"]+", "/Users/[you]", text.replace(str(Path.home()), "~"))


def build(target: Path) -> Path:
    """Write the bundle and return its folder."""
    target.mkdir(parents=True, exist_ok=False)
    doctor = _run([str(PKG / "install" / "doctor.command"), "--json"])
    payload = {
        "created_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release": json.loads((PKG / "RELEASE.json").read_text(encoding="utf-8")),
        "machine": machine(), "receipts": receipts(),
        "doctor": json.loads(doctor) if doctor.startswith("{") else {"unavailable": True},
        "install_log": (RUNTIME / "logs" / "install.log").read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        if (RUNTIME / "logs" / "install.log").exists() else [],
    }
    (target / "diagnostics.json").write_text(mask_home(json.dumps(payload, indent=2)) + "\n", encoding="utf-8")
    note = ("Contains: release and machine versions, the check report, install receipts and the installer's "
            "own step log. It does not contain footage, transcripts, edit plans, keys or logins.\n")
    (target / "README.txt").write_text(note, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = args.out or Path.home() / "Desktop" / f"sniper-diagnostics-{stamp}"
    folder = build(target)
    print(f"Support bundle written to {folder}\nRead it before you send it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
