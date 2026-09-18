"""Pre-seal current catalog/rate inputs before any OCI matrix probe executes."""
from __future__ import annotations

import hashlib
import os
import sys
from fractions import Fraction
from pathlib import Path

from cut_preview_io import digest, file_hash, read_bytes, write_new
from graphics.comp_capability_artifact import (
    MOTION_DIR, capability_digest, composition_paths, current_source_digest, load_artifact,
)
from graphics.comp_catalog_probe import probe_spec
from graphics.comp_rate_artifact import PROBE_FRAMES, RELEASED_RATES
from graphics.template_contract import declared_variables
from headless.container_io import CompositionInput, SealedInput, create_snapshot


def qualified_catalog() -> tuple[dict, list[Path]]:
    """Require the actual fresh registered inventory, never historical rows."""
    capabilities, issue = load_artifact(str(Path(MOTION_DIR) / "comp_capabilities.json"))
    if issue:
        raise RuntimeError(issue)
    paths = [Path(value) for value in composition_paths()]
    if set(capabilities) != {path.stem for path in paths}:
        raise RuntimeError("rate qualification catalog differs from capabilities")
    return capabilities, paths


def source_epoch(paths: set[Path]) -> dict:
    """Bind only selected source/runtime policy files, not unrelated Python edits."""
    rows = [{"path": str(path), "sha256": file_hash(path)} for path in sorted(paths)]
    return {"sha256": digest(rows), "files": rows, "motionDigest": current_source_digest()}


def execution_paths() -> set[Path]:
    """Capture imported graphics/OCI policy modules plus direct proof helpers."""
    result = set()
    for name, module in tuple(sys.modules.items()):
        selected = name.startswith(("graphics.", "headless.")) or name in {
            "cut_preview_io", "cross_runtime_canonical_json", "fingerprints"}
        value = getattr(module, "__file__", None)
        if selected and value and value.endswith(".py"):
            result.add(Path(value).resolve())
    return result


def _prepare_one(pipeline: str, source: Path, rate: str, directory: Path) -> dict:
    """Freeze defaults and selected local assets with an exact four-frame window."""
    html = read_bytes(source).decode("utf8")
    duration = Fraction(PROBE_FRAMES * 2 - 1, 2) / Fraction(rate)
    spec = probe_spec(source.stem, declared_variables(html))
    directory.mkdir(mode=0o700)
    relative = f"compositions/{source.name}"
    snapshot = create_snapshot(pipeline, CompositionInput(relative, html, duration=float(duration)), spec, str(directory))
    return {"kind": source.stem, "rate": rate, "composition": relative,
            "duration": {"numerator": str(duration.numerator), "denominator": str(duration.denominator)},
            "directory": str(directory), "inputSha256": snapshot.sha256,
            "inputSizeBytes": snapshot.size_bytes, "manifest": list(snapshot.manifest),
            "assetBindings": list(snapshot.asset_bindings), "specHash": digest(spec),
            "sourceSha256": hashlib.sha256(html.encode()).hexdigest()}


def _track_sources(row: dict, frozen: dict[Path, str]) -> None:
    """Every repeated dependency must have identical bytes across all archives."""
    for item in row["manifest"]:
        if not item["path"].startswith("motion/"):
            continue
        relative = item["path"][7:]
        path = Path(MOTION_DIR) / relative
        expected = row["sourceSha256"] if relative == row["composition"] else item["sha256"]
        if path in frozen and frozen[path] != expected:
            raise RuntimeError("motion dependency changed between sealed matrix requests")
        frozen[path] = expected


def prepare_inputs(directory: Path) -> tuple[dict, list[dict], set[Path]]:
    """Create all immutable archives first, then prove one unchanged source epoch."""
    capabilities, sources = qualified_catalog()
    before = current_source_digest()
    implementation = source_epoch(execution_paths())
    rows, paths, frozen = [], execution_paths() | set(sources), {}
    pipeline = str(Path(MOTION_DIR).parents[1])
    for source in sources:
        for rate in RELEASED_RATES:
            name = f"{len(rows):04d}-{source.stem}-{rate.replace('/', '_')}"
            row = _prepare_one(pipeline, source, rate, directory / name)
            rows.append(row)
            _track_sources(row, frozen)
            paths.update(Path(MOTION_DIR) / item["path"][7:] for item in row["manifest"]
                         if item["path"].startswith("motion/"))
    paths.add(Path(MOTION_DIR) / "comp_capabilities.json")
    if before != current_source_digest():
        raise RuntimeError("motion source changed during matrix input sealing")
    if source_epoch(execution_paths()) != implementation or any(file_hash(path) != expected for path, expected in frozen.items()):
        raise RuntimeError("source/runtime policy changed while sealing matrix inputs")
    epoch = source_epoch(paths)
    header = {"compositionKinds": sorted(capabilities), "sourceDigest": before,
              "capabilityDigest": capability_digest(capabilities), "sourceEpoch": epoch,
              "rates": list(RELEASED_RATES), "probeFrames": PROBE_FRAMES,
              "inputBytes": sum(row["inputSizeBytes"] for row in rows)}
    write_new(directory / "inputs.json", {"header": header, "requests": rows})
    os.chmod(directory / "inputs.json", 0o400)
    return header, rows, paths


def snapshot_for(row: dict) -> SealedInput:
    """Reconstitute only a previously sealed regular archive for the adapter."""
    return SealedInput(str(Path(row["directory"]) / "render-input.tar"), row["inputSha256"],
                       tuple(row["manifest"]), tuple(row["assetBindings"]), row["inputSizeBytes"])
