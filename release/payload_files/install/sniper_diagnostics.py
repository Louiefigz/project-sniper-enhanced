#!/usr/bin/env python3
"""Write a support bundle that is private by construction.

    install/diagnostics.command [--include-app-log]

The default bundle is built from structured facts, not from raw logs: release
identity, machine and tool versions, the doctor's report, install receipts
(versions and hashes), the installer's own step log, and *counts* of app-log
lines by kind. Raw app-log lines can carry transcript text, prompt text or a
token format nobody anticipated, so none is copied unless it is one of the
supervisor's own fixed-form status lines.

Paths are written relative to your home folder, and any other /Users/<name> is
masked, so your account name does not travel with the bundle.

`--include-app-log` adds the last 200 app-log lines after redaction. That is an
explicit choice the bundle's README records, because redaction by pattern cannot
promise to catch everything.
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
SUPERVISOR = re.compile(r"^\[sniper:supervisor\] (Could not (?:signal|launch) Next|Supervisor port lock was lost"
                        r"|The previous Next process group survived|Next stopped (?:repeatedly|unexpectedly))")
KINDS = (("error", re.compile(r"\berror\b", re.I)), ("warning", re.compile(r"\bwarn(?:ing)?\b", re.I)),
         ("ready", re.compile(r"\bReady in\b")), ("supervisor", re.compile(r"^\[sniper:supervisor\]")))
REDACT = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b(?:sk|ghp|ghu|gho|xox[abposr]|eyJ)[A-Za-z0-9_\-.]{8,}"), "[token]"),
    (re.compile(r"Bearer\s+\S+", re.I), "Bearer [token]"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "[long-value]"),
    (re.compile(r"/Users/[^/\s]+"), "/Users/[you]"),
)


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


def app_log_summary(path: Path) -> dict:
    """Counts by kind plus the supervisor's fixed-form lines; never free text."""
    if not path.exists():
        return {"present": False}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    counts = {name: sum(1 for line in lines if rule.search(line)) for name, rule in KINDS}
    fixed = [SUPERVISOR.match(line).group(0) for line in lines[-2000:] if SUPERVISOR.match(line)]
    return {"present": True, "lines": len(lines), "counts": counts, "supervisor_events": fixed[-20:]}


def redacted_tail(path: Path, count: int = 200) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:] if path.exists() else []
    out = []
    for line in lines:
        for rule, replacement in REDACT:
            line = rule.sub(replacement, line)
        out.append(line[:300])
    return out


def mask_home(text: str) -> str:
    """Replace this account's home folder, then any other account's, in serialized output."""
    return re.sub(r"/Users/[^/\s\"]+", "/Users/[you]", text.replace(str(Path.home()), "~"))


def build(target: Path, include_app_log: bool) -> Path:
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
        "app_log": app_log_summary(RUNTIME / "logs" / "app.log"),
        "app_log_included": include_app_log,
    }
    if include_app_log:
        payload["app_log_tail_redacted"] = redacted_tail(RUNTIME / "logs" / "app.log")
    (target / "diagnostics.json").write_text(mask_home(json.dumps(payload, indent=2)) + "\n", encoding="utf-8")
    note = ("Contains: release and machine versions, the check report, install receipts, the installer's "
            "own step log and counts of app-log lines. It does not contain footage, transcripts, edit "
            "plans, logins or app-log text")
    note += (". You chose --include-app-log: the last 200 app-log lines are included after pattern "
             "redaction, which cannot promise to remove everything — read them before sending.\n"
             if include_app_log else ".\n")
    (target / "README.txt").write_text(note, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-app-log", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = args.out or Path.home() / "Desktop" / f"sniper-diagnostics-{stamp}"
    folder = build(target, args.include_app_log)
    print(f"Support bundle written to {folder}\nRead it before you send it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
