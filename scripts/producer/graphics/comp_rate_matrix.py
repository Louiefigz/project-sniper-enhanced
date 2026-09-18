#!/usr/bin/env python3
"""Render/decode every registered composition at released rational rates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction

from fingerprints import file_sha256
from graphics.comp_capabilities import capability_matrix
from graphics.comp_capability_artifact import (
    capability_digest,
    composition_paths,
    composition_source_closure,
    current_source_digest,
)
from graphics.comp_catalog_probe import probe_spec
from graphics.comp_rate_artifact import (
    PROBE_FRAMES,
    RELEASED_RATES,
    validate_rate_matrix,
)
from graphics.composition_transform import set_root_duration
from graphics.graphics_render import (
    HYPERFRAMES_BIN,
    MOTION_DIR,
    NODE_USER_PRELOAD,
)
from graphics.hyperframes_invocation import RenderInvocation, render_composition
from graphics.render_rate import normalize_render_rate
from graphics.render_tools import resolve_tools
from graphics.template_contract import declared_variables

@dataclass(frozen=True)
class ProbeRequest:
    """One composition/rate render bound to the current source closure."""

    kind: str
    source: str
    rate: str
    scratch_root: str


def _read_source(path: str) -> tuple[str, str]:
    kind = os.path.splitext(os.path.basename(path))[0]
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    composition_source_closure(source)
    return kind, source


def _temp_name(request: ProbeRequest) -> str:
    digest = hashlib.sha256(
        f"{request.kind}\0{request.rate}".encode("ascii")).hexdigest()[:20]
    return f"_gs-rate-{digest}.html"


def _copy_link(source: str, destination: str) -> str:
    try:
        os.link(source, destination, follow_symlinks=False)
        return destination
    except OSError:
        return shutil.copy2(source, destination, follow_symlinks=False)


def _clone_motion_root(destination: str) -> None:
    ignored = shutil.ignore_patterns(
        "node_modules", "renders", "_gs-*", ".rate-probes-*")
    shutil.copytree(
        MOTION_DIR, destination, copy_function=_copy_link,
        ignore=ignored, symlinks=False)


def _probe_stream(path: str, rate: str, tools: dict[str, str]) -> dict:
    process = subprocess.run([
        tools["ffprobe"], "-v", "error", "-count_frames",
        "-select_streams", "v:0", "-show_entries",
        "stream=codec_name,pix_fmt,width,height,r_frame_rate,"
        "avg_frame_rate,nb_read_frames", "-of", "json", path,
    ], capture_output=True, text=True, timeout=30)
    if process.returncode:
        raise RuntimeError(f"ffprobe rejected rate probe: {process.stderr[-300:]}")
    try:
        streams = json.loads(process.stdout).get("streams") or []
        stream = streams[0] if len(streams) == 1 else None
        actual = Fraction(str(stream["avg_frame_rate"]))
        requested = Fraction(rate)
        frames = int(stream["nb_read_frames"])
    except (AttributeError, KeyError, TypeError, ValueError,
            ZeroDivisionError, json.JSONDecodeError) as exc:
        raise RuntimeError("rate probe metadata is malformed") from exc
    if actual != requested or Fraction(str(stream["r_frame_rate"])) != requested:
        raise RuntimeError(f"rate probe drifted: requested {rate}, got {actual}")
    if frames != PROBE_FRAMES:
        raise RuntimeError(
            f"rate probe decoded {frames} frames, expected {PROBE_FRAMES}")
    return {
        key: stream[key] for key in (
            "codec_name", "pix_fmt", "width", "height",
            "r_frame_rate", "avg_frame_rate", "nb_read_frames",
        )
    }


def _full_decode(path: str, tools: dict[str, str]) -> None:
    process = subprocess.run([
        tools["ffmpeg"], "-nostdin", "-v", "error", "-xerror",
        "-i", path, "-map", "0:v:0", "-f", "null", "-",
    ], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    if process.returncode:
        raise RuntimeError(f"full decode failed: {process.stderr[-300:]}")


def _write_probe_source(path: str, source: str, duration: Fraction) -> None:
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(set_root_duration(source, float(duration)))


def _remove_probe_source(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)


def probe_one(request: ProbeRequest) -> dict:
    """Render and fully decode one short, exact-rate composition sample."""
    normalized = normalize_render_rate(request.rate)
    duration = Fraction(
        (PROBE_FRAMES * 2 - 1) * normalized.denominator,
        2 * normalized.numerator,
    )
    name = _temp_name(request)
    tools = resolve_tools()
    spec = probe_spec(request.kind, declared_variables(request.source))
    with tempfile.TemporaryDirectory(
            prefix=f"{request.kind}-", dir=request.scratch_root) as scratch:
        project_root = os.path.join(scratch, "motion")
        _clone_motion_root(project_root)
        output = os.path.join(scratch, "probe.mov")
        temp_comp = os.path.join(project_root, "compositions", name)
        try:
            _write_probe_source(temp_comp, request.source, duration)
            render_composition(
                RenderInvocation(
                    project_root, f"compositions/{name}", "mov", spec,
                    output, request.rate),
                HYPERFRAMES_BIN, NODE_USER_PRELOAD)
            stream = _probe_stream(output, request.rate, tools)
            _full_decode(output, tools)
            return {
                "kind": request.kind, "rate": request.rate,
                "duration": {
                    "numerator": str(duration.numerator),
                    "denominator": str(duration.denominator),
                },
                "stream": stream, "mediaSha256": file_sha256(output),
                "decoded": True,
            }
        finally:
            _remove_probe_source(temp_comp)


def _tool_receipts() -> dict:
    return {
        name: {"path": path, "sha256": file_sha256(path)}
        for name, path in sorted(resolve_tools().items())
    }


def build_matrix(kinds: set[str], rates: tuple[str, ...],
                 workers: int, scratch_root: str) -> dict:
    """Execute the selected cross-product and return one retained receipt."""
    sources = dict(_read_source(path) for path in composition_paths())
    unknown = sorted(kinds - set(sources))
    if unknown:
        raise ValueError(f"unknown composition kinds: {unknown}")
    selected = sorted(kinds or set(sources))
    requests = [
        ProbeRequest(kind, sources[kind], rate, scratch_root)
        for kind in selected for rate in rates
    ]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        probes = list(pool.map(probe_one, requests))
    value = {
        "schemaVersion": 1,
        "kind": "hyperframes-released-rate-matrix",
        "passed": True,
        "sourceDigest": current_source_digest(),
        "capabilityDigest": capability_digest(capability_matrix()),
        "rates": list(rates),
        "compositionCount": len(selected),
        "probeFrames": PROBE_FRAMES,
        "tools": _tool_receipts(),
        "probes": sorted(probes, key=lambda row: (row["kind"], row["rate"])),
    }
    value["receiptHash"] = hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    issue = validate_rate_matrix(value, value["tools"], None)
    if issue:
        raise RuntimeError(f"generated rate matrix failed its contract: {issue}")
    return value


def _write(path: str, value: dict) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    descriptor, staged = tempfile.mkstemp(prefix=".rate-matrix-", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(staged):
            os.remove(staged)


def main() -> int:
    """CLI for the opt-in, real-browser released-rate acceptance matrix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--scratch-root")
    parser.add_argument("--kind", action="append", default=[])
    parser.add_argument("--rate", action="append", default=[])
    args = parser.parse_args()
    rates = tuple(args.rate or RELEASED_RATES)
    for rate in rates:
        normalize_render_rate(rate)
    if args.workers < 1 or args.workers > 4:
        raise SystemExit("--workers must be between 1 and 4")
    with tempfile.TemporaryDirectory(
            prefix="sniper-rate-matrix-",
            dir=args.scratch_root) as scratch:
        value = build_matrix(
            set(args.kind), rates, args.workers, scratch)
    _write(args.out, value)
    print(json.dumps({
        "passed": True, "compositions": value["compositionCount"],
        "rates": len(rates), "probes": len(value["probes"]),
        "receiptHash": value["receiptHash"], "out": args.out,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
