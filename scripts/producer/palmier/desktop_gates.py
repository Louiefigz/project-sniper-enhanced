"""Run the cheap deterministic gates before a Desktop Palmier stage unlocks."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from fingerprints import file_sha256
from palmier.desktop_state import DesktopStageInput
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import atomic_write_record

GATES_NAME = ".palmier-desktop-gates"


def _command(script: str, *args: str) -> list[str]:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [sys.executable, os.path.join(root, script), *args]


def _run(name: str, command: list[str]) -> dict:
    timeout = float(os.environ.get("SNIPER_DESKTOP_GATE_TIMEOUT_S", "300"))
    try:
        process = subprocess.run(command, capture_output=True, text=True,
                                 check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"name": name, "ok": False, "exitCode": None,
                "verdict": {"ok": False, "errors": [
                    f"gate exceeded {timeout:.0f}s timeout"]}, "stderr": ""}
    output = process.stdout.strip()
    try:
        verdict = json.loads(output) if output else {}
    except json.JSONDecodeError:
        verdict = {"ok": False, "errors": [
            f"{name} emitted invalid JSON: {output[-300:]}"]}
    return {"name": name, "ok": process.returncode == 0
            and verdict.get("ok") is True, "exitCode": process.returncode,
            "verdict": verdict, "stderr": process.stderr.strip()[-1000:]}


def _parallel(commands: list[tuple[str, list[str]]]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        futures = [pool.submit(_run, name, command)
                   for name, command in commands]
        return [future.result() for future in futures]


def run_desktop_gates(inputs: DesktopStageInput) -> dict:
    """Persist one hash-bound gate receipt or fail without unlocking Palmier."""
    transcripts = os.path.abspath(inputs.transcripts_dir or
                                   os.path.dirname(inputs.manifest_path))
    if inputs.stage == "cut":
        rows = [_run("transcript-cut-previsual", _command(
            "transcript_cut_contract.py", inputs.plan_path, transcripts,
            inputs.manifest_path, "--previsual"))]
    else:
        rows = _parallel([
            ("plan-lint", _command(
                "plan_lint.py", inputs.plan_path, inputs.manifest_path,
                transcripts)),
            ("hook-contract", _command(
                "hook_contract.py", inputs.plan_path, transcripts,
                inputs.manifest_path)),
            ("claims-contract", _command(
                "claims_contract.py", inputs.plan_path, transcripts,
                inputs.manifest_path)),
        ])
    receipt = {
        "schemaVersion": 1, "kind": "palmier-desktop-gates",
        "stage": inputs.stage, "planHash": file_sha256(inputs.plan_path),
        "manifestHash": file_sha256(inputs.manifest_path), "gates": rows,
        "ok": all(row["ok"] for row in rows),
    }
    blob = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    path = os.path.join(inputs.out_dir, f"{GATES_NAME}.{digest[:16]}.json")
    atomic_write_record(path, receipt)
    if not receipt["ok"]:
        failed = ", ".join(row["name"] for row in rows if not row["ok"])
        raise PalmierError(f"Desktop Palmier stage gates failed: {failed}")
    return {"path": path, "hash": file_sha256(path), "content": receipt}
