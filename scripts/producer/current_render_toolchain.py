"""Exact source/runtime closure used by the current-render graph bridge."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from current_render_graph_contract import file_hash, object_hash
from graphics.render_tools import resolve_tools
from render_effect_discovery import (
    local_python_import_closure,
    renderer_import_closure,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
MOTION_ROOT = PROJECT_ROOT / "templates" / "motion"
_SURGICAL_ENTRYPOINTS = (
    SCRIPT_DIR / "edit" / "cut_repair_surgical_terminal.py",
    SCRIPT_DIR / "current_render_graph_candidate.py",
    SCRIPT_DIR / "current_render_graph_candidate_cli.py",
)


def _files(root: Path, suffixes: set[str]) -> list[Path]:
    return [
        path for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
        and path.suffix in suffixes and "__pycache__" not in path.parts
        and "tests" not in path.parts
    ]


def _tool_file(name: str) -> Path:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"current render graph cannot resolve {name}")
    return Path(os.path.realpath(resolved))


def current_toolchain_python_files() -> list[Path]:
    """Bind normal rendering plus surgical staging/promotion transitive code."""
    return sorted(set(
        renderer_import_closure()
        + local_python_import_closure(list(_SURGICAL_ENTRYPOINTS))))


def current_toolchain_hash() -> str:
    """Hash renderer source, motion runtime, and exact media/browser binaries."""
    paths = current_toolchain_python_files()
    paths += _files(MOTION_ROOT / "compositions", {".html"})
    for relative in (
        "tokens.css", "motion-tokens.js", "vendor/gsap/gsap.min.js",
        "node_modules/hyperframes/dist/cli.js", "hyperframes.json",
        "index.html", "package.json",
    ):
        path = MOTION_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"render toolchain input is unavailable: {path}")
        paths.append(path)
    paths.append(SCRIPT_DIR / "headless" / "node_isolated_user.cjs")
    paths += [Path(os.path.realpath(path))
              for path in resolve_tools().values()]
    paths += [_tool_file(name) for name in ("ffmpeg", "ffprobe", "node")]
    paths.append(Path(os.path.realpath(sys.executable)))
    rows = [{"path": str(path.resolve()), "sha256": file_hash(path)}
            for path in sorted(set(paths))]
    return object_hash({
        "domain": "sniper-current-render-toolchain-v1", "files": rows,
    })
