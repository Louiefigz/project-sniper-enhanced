"""Opt-in phase timing of ONE sealed four-frame OCI probe; no policy bypass.

The wrappers call the existing implementation unchanged, record monotonic phase
durations, and read the bounded CLI log before its normal owned cleanup.
"""
from __future__ import annotations

import argparse
import json
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from cut_preview_io import digest, file_hash, write_new
from color import deadline as diagnostic_deadline
from graphics import comp_rate_oci
from graphics.comp_rate_oci_inputs import _prepare_one, execution_paths, qualified_catalog, source_epoch
from headless import container_policy, container_renderer


def _timed(name: str, target: Callable, phases: list[dict]) -> Callable:
    """Measure a policy call without changing its arguments, result, or failure."""
    def call(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            return target(*args, **kwargs)
        finally:
            phases.append({"phase": name, "elapsedMs": round((time.monotonic() - started) * 1000)})
    return call


def _wait_with_log(target: Callable, evidence: dict) -> Callable:
    """Read at most4096 trusted CLI-log bytes after the original wait/copy."""
    def call(*args: Any, **kwargs: Any) -> Any:
        with diagnostic_deadline.wall_budget(time.monotonic() + 120):
            result = target(*args, **kwargs)
            log = container_policy._exec_tail(args[0], args[1], args[2], "/output/render.log")
            evidence["rendererLogTail"] = log.stdout if log.returncode == 0 else "unavailable"
        return result
    return call


def _instrument(stack: ExitStack, evidence: dict) -> None:
    """Observe existing OCI checks, launch, render wait, cleanup, and proof phases."""
    phases = evidence["phases"]
    names = ("attest_image", "daemon_identity", "_run", "attest_container", "probe_container",
             "remove_container", "_promote_outputs")
    for name in names:
        stack.enter_context(patch.object(container_renderer, name, _timed(name, getattr(container_renderer, name), phases)))
    wait = _timed("render_wait_copy_and_log", _wait_with_log(container_renderer.wait_and_copy, evidence), phases)
    stack.enter_context(patch.object(container_renderer, "wait_and_copy", wait))
    for name in ("_probe_stream", "_full_decode"):
        stack.enter_context(patch.object(comp_rate_oci, name, _timed(name, getattr(comp_rate_oci, name), phases)))


def profile(kind: str, rate: str, directory: Path) -> dict:
    """Create and time exactly one fresh registered probe with sealed source proof."""
    started = time.monotonic()
    capabilities, sources = qualified_catalog()
    if kind not in capabilities or rate not in comp_rate_oci.RELEASED_RATES:
        raise RuntimeError("profile kind/rate is not registered/released")
    root = Path(__file__).resolve().parents[3]
    paths = execution_paths() | {Path(__file__).resolve(), Path(comp_rate_oci.__file__).resolve(),
                                 Path(diagnostic_deadline.__file__).resolve()}
    before = source_epoch(paths)
    directory.mkdir(mode=0o700, exist_ok=False)
    source = next(path for path in sources if path.stem == kind)
    request = _prepare_one(str(root), source, rate, directory / "probe")
    tools, proof = comp_rate_oci.proof_tools()
    evidence = {"schemaVersion": 1, "kind": "single-oci-rate-phase-diagnostic", "passed": False,
                "sourceEpoch": before, "request": request, "proofTools": proof, "phases": [], "renderWaitWorkBudgetS": 120,
                "runnerAtStartSha256": file_hash(Path(__file__).resolve()), "setupMs": round((time.monotonic() - started) * 1000)}
    write_new(directory / "context.json", evidence)
    try:
        with ExitStack() as stack:
            _instrument(stack, evidence)
            evidence["probe"] = comp_rate_oci._probe(request, tools, capabilities[kind]["canvas"])
        if source_epoch(paths) != before or comp_rate_oci.proof_tools()[1] != proof:
            raise RuntimeError("phase diagnostic source or proof-tool identity changed")
        evidence["passed"] = True
    except (OSError, RuntimeError, ValueError) as exc:
        evidence["error"] = str(exc)
    evidence["elapsedMs"] = round((time.monotonic() - started) * 1000)
    evidence["receiptHash"] = digest(evidence)
    write_new(directory / "profile.json", evidence)
    return evidence


def main() -> None:
    """Require explicit registered kind/rate and a fresh private output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind")
    parser.add_argument("rate")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = profile(args.kind, args.rate, Path(args.out).absolute())
    print(json.dumps({key: result.get(key) for key in ("passed", "phases", "rendererLogTail", "elapsedMs", "error")}), flush=True)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
