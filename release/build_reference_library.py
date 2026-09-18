#!/usr/bin/env python3
"""Render and write the packaged reference library from its original spec.

    python3 -m release.build_reference_library      # same as: python3 -m release.reference_library_writer

Rewrites `resources/references/` completely (see `release/reference_library_writer.py`).

Every frame comes from a Project Sniper motion template rendered by the pinned
HyperFrames CLI with copy from `release/reference_library_spec.py`. Each frame's
composition, variables and time are recorded next to its hash, so the library can
be regenerated and audited. Maintainer tooling; the output ships, this does not.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from release import reference_library_spec as spec

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / "templates" / "motion"
_VARS = re.compile(r"data-composition-variables='(\[.*?\])'", re.S)
_SKIP = ("node_modules", ".sniper-native-runtime", "renders", "reference", "container")
FRAME_WIDTH_PORTRAIT, FRAME_WIDTH_LANDSCAPE = 720, 1280


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _project(workspace: Path) -> Path:
    """A throwaway copy of the motion project that renders one composition."""
    project = workspace / "project"
    shutil.copytree(MOTION, project, ignore=shutil.ignore_patterns(*_SKIP))
    (project / "node_modules").symlink_to(MOTION / "node_modules")
    return project


def _set_defaults(template: str, overrides: dict) -> str:
    """Rewrite the composition's variable defaults to the spec's original copy."""
    found = _VARS.search(template)
    if not found:
        raise RuntimeError("composition declares no variables")
    rows = json.loads(html.unescape(found.group(1)))
    known = {row["id"] for row in rows}
    unknown = set(overrides) - known
    if unknown:
        raise RuntimeError(f"unknown variables {sorted(unknown)}")
    for row in rows:
        if row["id"] in overrides:
            row["default"] = overrides[row["id"]]
    encoded = json.dumps(rows, ensure_ascii=False).replace("'", "&#39;")
    return template[:found.start(1)] + encoded + template[found.end(1):]


def _dimensions(image: Path) -> list[int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", str(image)],
                         capture_output=True, text=True, check=True).stdout.strip()
    width, height = (int(value) for value in out.split(","))
    return [width, height]


def render(composition: str, overrides: dict, times: tuple[float, ...],
           asset: Path | None = None) -> list[Path]:
    """Render one composition at three times; return temporary PNG paths."""
    workspace = Path(tempfile.mkdtemp(prefix="sniper-reflib-"))
    project = _project(workspace)
    source = (MOTION / "compositions" / f"{composition}.html").read_text(encoding="utf-8")
    if asset is not None:
        shutil.copyfile(asset, project / "assets" / asset.name)
        overrides = {**overrides, "image": f"assets/{asset.name}"}
    (project / "index.html").write_text(_set_defaults(source, overrides), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
    env.update(HYPERFRAMES_NO_TELEMETRY="1", HYPERFRAMES_NO_UPDATE_CHECK="1",
               HYPERFRAMES_NO_AUTO_INSTALL="1")
    out = workspace / "out"
    subprocess.run([str(MOTION / "node_modules/.bin/hyperframes"), "snapshot", str(project),
                    "--at", ",".join(f"{t:g}" for t in times), "--no-end",
                    "--describe", "false", "-o", str(out)],
                   check=True, capture_output=True, env=env)
    frames = sorted(out.glob("frame-*.png"))
    if len(frames) != len(times):
        raise RuntimeError(f"{composition}: expected {len(times)} frames, got {len(frames)}")
    return frames


def to_jpeg(png: Path, target: Path) -> None:
    """Scale to the library width and encode a stable JPEG."""
    width = _dimensions(png)[0]
    scaled = FRAME_WIDTH_PORTRAIT if width < 1500 else FRAME_WIDTH_LANDSCAPE
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(png), "-vf", f"scale={scaled}:-2",
                    "-q:v", "3", "-bitexact", str(target)], check=True)


def frame_records(frames_dir: Path, stem: str, pngs: list[Path], times: tuple[float, ...],
                  provenance: dict) -> list[dict]:
    """Encode and describe the rendered frames for one beat."""
    rows = []
    for index, (png, when) in enumerate(zip(pngs, times)):
        target = frames_dir / f"{stem}-{index}.jpg"
        to_jpeg(png, target)
        rows.append({"path": target.relative_to(ROOT).as_posix(), "sha256": _digest(target),
                     "dimensions": _dimensions(target), "requested_time": when,
                     "render": {**provenance, "time_s": when}})
    return rows


if __name__ == "__main__":
    from release.reference_library_writer import build  # noqa: PLC0415 - the writer imports this module
    print(json.dumps(build(), indent=2))
