"""Exact current caption identity projections using already bounded held bytes.

These match existing compiler/page identity formats, without their unguarded
file reads. No font/model discovery command or media process is launched.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import captions.caption_fingerprints as compiler
import captions.caption_pages as page_planner
from captions.caption_fingerprints import canonical_digest
from captions.caption_plan_pipeline import PROJECTION_TOOLCHAIN
from guided_caption_dependencies import (CaptionFile, Guard, MAX_FILE_BYTES, MAX_TOTAL_BYTES,
                                         hold_caption_file)


def tool_paths() -> dict[str, Path]:
    """Resolve exactly the same installed tools as the actual caption renderer."""
    result = {}
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if not path:
            raise RuntimeError("held caption cannot resolve " + name)
        result[name] = Path(path).resolve(strict=True)
    return result


def code_paths() -> tuple[Path, ...]:
    """Require the full compiler inventory; missing code is not silently skipped."""
    directory = Path(compiler.__file__).resolve().parent
    result = [(directory / name).resolve(strict=True) for name in compiler._COMPILER_SOURCES]
    result.extend(Path(path) for path in page_planner.caption_page_implementation_paths().values())
    result.extend(Path(__file__).with_name(name) for name in ("guided_caption_identity.py",
        "guided_caption_projection.py", "guided_caption_projection_contract.py", "guided_caption_dependencies.py"))
    return tuple(sorted(set(result)))


def external_paths(data: dict) -> dict[str, str | None]:
    """Exact declared font/fontconfig refs plus fixed local tool/code dependencies."""
    closure = data["shards"]["fontClosure"]
    values = [*closure["tools"].values(), *closure["files"]]
    if len(values) > 256:
        raise RuntimeError("held caption external font inventory exceeds its bound")
    result = {str(path): None for path in (*code_paths(), *tool_paths().values())}
    for value in values:
        expected = value["sha256"]
        prior = result.get(value["path"])
        if prior is not None and prior != expected:
            raise RuntimeError("held caption external identities conflict")
        result[value["path"]] = expected
    return result


def capture_external(data: dict, guard: Guard) -> tuple[CaptionFile, ...]:
    """Observe bounded current bytes, comparing every externally declared hash."""
    paths = external_paths(data)
    sizes = {path: Path(path).lstat().st_size for path in paths}
    if any(not 0 < size <= MAX_FILE_BYTES for size in sizes.values()) or sum(sizes.values()) > MAX_TOTAL_BYTES:
        raise RuntimeError("held caption external dependencies exceed byte admission")
    result = []
    for path, expected in sorted(paths.items()):
        if Path(path).lstat().st_size != sizes[path]:
            raise RuntimeError("held caption external preflight size changed")
        row = hold_caption_file(Path(path), guard, sizes[path])
        if expected is not None and row.sha256 != expected:
            raise RuntimeError("held caption font/tool dependency differs")
        result.append(row)
    return tuple(result)


def projection_identities(rows: tuple[CaptionFile, ...]) -> dict:
    """Reproduce existing identity domains from independently rechecked raw hashes."""
    held = {row.path: row for row in rows}
    directory = Path(compiler.__file__).resolve().parent
    sources = [{"name": name, "sha256": held[str((directory / name).resolve(strict=True))].sha256}
               for name in compiler._COMPILER_SOURCES]
    compiler_hash = canonical_digest("sniper-caption-compiler-v1", {"sources": sources, "toolchain": PROJECTION_TOOLCHAIN})
    tools = {name: {"path": str(path), "sha256": held[str(path)].sha256} for name, path in tool_paths().items()}
    implementation = {name: held[path].sha256
                      for name, path in page_planner.caption_page_implementation_paths().items()}
    compositor = canonical_digest("sniper-caption-alpha-page-compositor-v1", {"tools": tools,
        "codec": "png", "pixelFormat": "rgba", "alphaMode": "straight", "implementation": implementation})
    return {"compiler": compiler_hash, "tools": tools, "compositor": compositor}
