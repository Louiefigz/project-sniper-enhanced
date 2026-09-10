"""Opt-in retained short/LF-14 dirty-scene versus forced-full acceptance."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from current_render_graph_contract import file_hash
from current_render_oracle import prove
from current_render_toolchain import current_toolchain_hash
from render_effect_registry import registry_hash

SCRIPT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SCRIPT_DIR.parents[1]
GRAPH = SCRIPT_DIR / "current_render_graph_cli.py"
ASSEMBLE = SCRIPT_DIR / "assemble.py"
BASELINES = PROJECT_ROOT / "artifacts" / "p0-current-baselines-20260729"
_LIVE = os.environ.get("RUN_LIVE_RENDER_EFFECT_BASELINES") == "1"
_EVIDENCE_ROOT = os.environ.get("RENDER_EFFECT_BASELINE_EVIDENCE_ROOT")
_CASES = tuple(filter(None, os.environ.get(
    "RENDER_EFFECT_BASELINE_CASES", "short,lf14").split(",")))


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise RuntimeError(f"retained baseline document is not an object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _plan(baseline: Path, text: str | None) -> dict:
    plan = _read(baseline / "edit_plan.json")
    if text is None:
        plan["graphicsTrack"] = []
        return plan
    mode = plan["target"]["mode"]
    plan["graphicsTrack"] = [{
        "kind": "text-element" if mode == "short" else "text-element-wide",
        "anchor": "free-band", "outStart": 3.0, "outEnd": 6.0,
        "reason": "retained dirty-scene parity control",
        "spec": {
            "text": text, "align": "center", "color": "#FFFFFF",
            "fontSize": 64, "weight": 700,
        },
    }]
    return plan


def _link(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _producer(
    root: Path, baseline: Path, plan: dict, seed_final: bool,
) -> tuple[Path, Path]:
    root.mkdir()
    _link(baseline / "render" / "base_final.mp4", root / "base_final.mp4")
    shutil.copy2(baseline / "render" / "timeline_map.json",
                 root / "timeline_map.json")
    if seed_final:
        _link(baseline / "render" / "final.mp4", root / "final.mp4")
    plan_path = root / "edit_plan.json"
    _write(plan_path, plan)
    (root / "scene-cache").mkdir()
    return plan_path, root / "final.mp4"


def _graph_prefix(
    producer: Path, plan: Path, manifest: Path, output: Path,
) -> list[str]:
    return [
        sys.executable, str(GRAPH), "--phase", "assemble",
        "--producer-dir", str(producer), "--plan", str(plan),
        "--manifest", str(manifest), "--base",
        str(producer / "base_final.mp4"), "--output", str(output),
        "--cache-dir", str(producer / "scene-cache"),
    ]


def _seed_command(
    producer: Path, plan: Path, manifest: Path, output: Path,
) -> list[str]:
    return [*_graph_prefix(producer, plan, manifest, output),
            "--", "/usr/bin/true"]


def _assemble_command(
    producer: Path, plan: Path, manifest: Path, output: Path,
    forced: bool = False,
) -> list[str]:
    child = [
        str(ASSEMBLE), str(producer / "base_final.mp4"), str(plan),
        str(output), "--manifest", str(manifest),
        "--require-source-set-admission", "--cache-dir",
        str(producer / "scene-cache"),
    ]
    prefix = _graph_prefix(producer, plan, manifest, output)
    if forced:
        prefix.append("--force-full")
    return [*prefix, "--", *child]


def _run(command: list[str], evidence: Path, name: str) -> float:
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=SCRIPT_DIR, capture_output=True, text=True)
    elapsed = round(time.monotonic() - started, 3)
    (evidence / f"{name}.stdout.ndjson").write_text(
        result.stdout, encoding="utf-8")
    (evidence / f"{name}.stderr.log").write_text(
        result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-16000:])
    return elapsed


def _active(producer: Path) -> tuple[dict, dict]:
    root = producer / ".render-graph-v1"
    pointer = _read(root / "ACTIVE.json")
    generation = root / "generations" / pointer["graphHash"]
    graph = _read(generation / "graph.json")
    receipt = _read(
        generation / "receipts" / f"{pointer['receiptHash']}.json")
    return graph, receipt


@contextmanager
def _workspace(name: str) -> Iterator[Path]:
    if _EVIDENCE_ROOT:
        root = Path(_EVIDENCE_ROOT).resolve() / name
        root.mkdir(parents=True, exist_ok=False)
        yield root
        return
    with tempfile.TemporaryDirectory() as temporary:
        yield Path(temporary).resolve()


def _incremental_arm(
    root: Path, baseline: Path, manifest: Path,
) -> dict:
    producer = root / "incremental"
    plan, output = _producer(
        producer, baseline, _plan(baseline, None), True)
    timings = {
        "seedSeconds": _run(
            _seed_command(producer, plan, manifest, output),
            root, "01-seed"),
    }
    _write(plan, _plan(baseline, "AFTER"))
    timings["incrementalSeconds"] = _run(
        _assemble_command(producer, plan, manifest, output),
        root, "02-incremental")
    graph, receipt = _active(producer)
    return {
        "output": output, "graph": graph,
        "receipt": receipt, "timings": timings,
    }


def _forced_arm(root: Path, baseline: Path, manifest: Path) -> dict:
    producer = root / "forced"
    plan, output = _producer(
        producer, baseline, _plan(baseline, "AFTER"), False)
    elapsed = _run(
        _assemble_command(producer, plan, manifest, output, True),
        root, "03-forced-full")
    graph, receipt = _active(producer)
    return {
        "output": output, "graph": graph,
        "receipt": receipt, "seconds": elapsed,
    }


def _run_case(name: str, root: Path) -> dict:
    registry_at_start = registry_hash()
    baseline = BASELINES / name
    if not baseline.is_dir():
        raise RuntimeError(f"retained baseline is unavailable: {baseline}")
    shutil.copy2(baseline / "project.json", root / "project.json")
    manifest = baseline / "asset_manifest.json"
    incremental = _incremental_arm(root, baseline, manifest)
    forced = _forced_arm(root, baseline, manifest)
    started = time.monotonic()
    oracle = prove(
        incremental["output"], forced["output"], root / "04-oracle.json")
    timings = {
        **incremental["timings"],
        "forcedFullSeconds": forced["seconds"],
        "oracleSeconds": round(time.monotonic() - started, 3),
    }
    captured_toolchain = incremental["graph"]["toolchainHash"]
    forced_toolchain = forced["graph"]["toolchainHash"]
    observed_toolchain = current_toolchain_hash()
    result = {
        "schemaVersion": 1, "kind": "render-effect-dirty-forced-parity",
        "baseline": name,
        "baselinePlanSha256": file_hash(baseline / "edit_plan.json"),
        "manifestSha256": file_hash(manifest),
        "incrementalGraphHash": incremental["receipt"]["graphHash"],
        "toolchainHash": captured_toolchain,
        "forcedToolchainHash": forced_toolchain,
        "currentToolchainHash": observed_toolchain,
        "toolchainFresh": (
            captured_toolchain == forced_toolchain == observed_toolchain),
        "registryHash": registry_at_start,
        "registryFresh": registry_at_start == registry_hash(),
        "incrementalFinalSha256": file_hash(incremental["output"]),
        "forcedFinalSha256": file_hash(forced["output"]),
        "dirtyNodeIds": incremental["receipt"]["dirtyNodeIds"],
        "reusedNodeIds": incremental["receipt"]["reusedNodeIds"],
        "forcedExecutionMode": forced["receipt"]["executionMode"],
        "oraclePassed": oracle["passed"], "timings": timings,
        "graphNodeCount": len(incremental["graph"]["nodes"]),
    }
    _write(root / "render-effect-parity-summary-v1.json", result)
    return result


@unittest.skipUnless(_LIVE, "set RUN_LIVE_RENDER_EFFECT_BASELINES=1")
class LiveRenderEffectBaselineParity(unittest.TestCase):
    def test_retained_short_and_lf14_dirty_scene_match_forced_full(self) -> None:
        results = []
        for name in _CASES:
            with self.subTest(baseline=name), _workspace(name) as root:
                result = _run_case(name, root)
                results.append(result)
                self.assertEqual(result["dirtyNodeIds"], [
                    "node-scene-0000", "node-composite", "node-final"])
                self.assertEqual(result["reusedNodeIds"], [
                    "node-source", "node-timeline", "node-base"])
                self.assertEqual(
                    result["forcedExecutionMode"], "forced-full")
                self.assertTrue(result["oraclePassed"])
                self.assertTrue(result["toolchainFresh"])
                self.assertTrue(result["registryFresh"])
        self.assertEqual(
            {row["toolchainHash"] for row in results},
            {current_toolchain_hash()})
        self.assertEqual(
            {row["registryHash"] for row in results}, {registry_hash()})


if __name__ == "__main__":
    unittest.main(verbosity=2)
