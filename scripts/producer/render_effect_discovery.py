#!/usr/bin/env python3
"""Static plan/manifest reader discovery for the renderer import closure."""
from __future__ import annotations

import ast
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from render_effect_registry import PROJECT_ROOT, load_registry

PRODUCER_ROOT = PROJECT_ROOT / "scripts" / "producer"


def _module_name(path: Path) -> str:
    """Use the same local package spelling for discovered and required sources."""
    relative = path.relative_to(PRODUCER_ROOT).as_posix()
    return relative.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def _python_files() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in PRODUCER_ROOT.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        result[_module_name(path)] = path
    return result


def _required_modules(modules: dict[str, Path], sources: list[Path]) -> None:
    """Original local imports cannot disappear from a mutable directory listing."""
    for path in sources:
        module = _module_name(path)
        if module in modules and modules[module] != path:
            raise RuntimeError(f"render discovery required module has an ambiguous local path: {module}")
        modules[module] = path


def _import_candidates(path: Path, node: ast.ImportFrom) -> list[str]:
    relative = path.relative_to(PRODUCER_ROOT)
    package = list(relative.parent.parts)
    if node.level:
        keep = len(package) - (node.level - 1)
        if keep < 0:
            return []
        prefix = package[:keep]
        module = prefix + (node.module.split(".") if node.module else [])
    else:
        module = node.module.split(".") if node.module else []
    base = ".".join(module)
    candidates = [
        ".".join([*module, alias.name]) for alias in node.names
        if alias.name != "*"
    ]
    if base:
        candidates.append(base)
    return candidates


def _import_names(path: Path, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return _import_candidates(path, node)
    return []


def _resolve_import(name: str, modules: dict[str, Path]) -> Path | None:
    parts = name.split(".")
    for count in range(len(parts), 0, -1):
        resolved = modules.get(".".join(parts[:count]))
        if resolved is not None:
            return resolved
    return None


def _imports(path: Path, modules: dict[str, Path], source: str | None = None) -> list[Path]:
    tree = ast.parse(path.read_text(encoding="utf-8") if source is None else source)
    found: list[Path] = []
    for node in ast.walk(tree):
        found.extend(
            resolved for name in _import_names(path, node)
            if (resolved := _resolve_import(name, modules)) is not None
        )
    return found


def local_python_import_closure(entrypoints: list[Path], read_source: Callable[[Path], str] | None = None,
                              required_sources: list[Path] | None = None) -> list[Path]:
    """Walk exact entrypoints with optional authenticated text/original module inventory."""
    modules = _python_files()
    if required_sources is not None:
        _required_modules(modules, required_sources)
    pending = list(entrypoints)
    reached: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in reached:
            continue
        if not path.is_file():
            raise RuntimeError(f"render discovery entrypoint is missing: {path}")
        reached.add(path)
        imports = _imports(path, modules) if read_source is None else _imports(path, modules, read_source(path))
        pending.extend(imports)
    return sorted(reached)


def renderer_import_closure() -> list[Path]:
    """Return every repository Python module reachable from graph entrypoints."""
    registry = load_registry()
    return local_python_import_closure([
        PROJECT_ROOT / relative
        for relative in registry["discovery"]["entrypoints"]
    ])


def _object_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _object_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal_read(node: ast.AST) -> tuple[str, str] | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args:
        key = node.args[0]
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return _object_name(node.func.value), key.value
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
            and isinstance(node.slice.value, str):
        return _object_name(node.value), node.slice.value
    return None


def _script_dir_join(node: ast.Call) -> Path | None:
    if _object_name(node.func) != "os.path.join" or not node.args:
        return None
    if not isinstance(node.args[0], ast.Name) \
            or node.args[0].id != "SCRIPT_DIR":
        return None
    parts: list[str] = []
    for item in node.args[1:]:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        parts.append(item.value)
    if not parts or not parts[-1].endswith(".py"):
        return None
    return Path(os.path.normpath(PRODUCER_ROOT.joinpath(*parts)))


def _referenced_paths(path: Path) -> set[Path]:
    found: set[Path] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        joined = _script_dir_join(node)
        if joined is not None:
            found.add(joined)
        if _object_name(node.func) != "_run_stage_cli" or not node.args:
            continue
        script = node.args[0]
        valid = isinstance(script, ast.Constant) \
            and isinstance(script.value, str) \
            and script.value.endswith(".py")
        if valid:
            found.add(PRODUCER_ROOT / script.value)
    return found


def referenced_python_paths() -> set[Path]:
    """Find Python files invoked/read by path rather than imported."""
    found: set[Path] = set()
    for path in renderer_import_closure():
        found.update(_referenced_paths(path))
    return found


def _document_name(object_name: str) -> str | None:
    if object_name in {"plan", "ctx.plan", "job.plan"}:
        return "plan"
    if object_name in {"manifest", "ctx.manifest"}:
        return "manifest"
    return None


def _root_reads(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    for node in ast.walk(tree):
        read = _literal_read(node)
        if read is None:
            continue
        object_name, key = read
        document = _document_name(object_name)
        if document is not None:
            rows.append({
                "document": document, "path": relative,
                "key": key, "line": getattr(node, "lineno", 0),
            })
    return rows


def discover_root_reads() -> list[dict[str, Any]]:
    """Discover literal reads on plan/job.plan/ctx.plan and asset manifests."""
    rows: list[dict[str, Any]] = []
    for path in renderer_import_closure():
        rows.extend(_root_reads(path))
    return rows


def discovery_gaps() -> list[str]:
    """Return unregistered reads or stale non-asset-manifest exceptions."""
    registry = load_registry()
    documents = registry["documents"]
    exclusions = registry["discovery"]["nonAssetManifestReads"]
    observed_exclusions: set[tuple[str, str]] = set()
    gaps: list[str] = []
    for row in discover_root_reads():
        document, path, key = row["document"], row["path"], row["key"]
        if document == "manifest" and key in exclusions.get(path, []):
            observed_exclusions.add((path, key))
            continue
        allowed = set(documents[document]["rootFields"])
        private = key.startswith(documents[document]["privatePrefix"])
        if key not in allowed and not private:
            gaps.append(f"{path}:{row['line']} reads unregistered {document}.{key}")
    declared = {
        (path, key) for path, keys in exclusions.items() for key in keys
    }
    for path, key in sorted(declared - observed_exclusions):
        gaps.append(f"stale non-asset manifest exclusion: {path}:{key}")
    closure = set(renderer_import_closure())
    for path in sorted(referenced_python_paths() - closure):
        gaps.append(
            "path-invoked Python is outside renderer closure: "
            f"{path.relative_to(PROJECT_ROOT).as_posix()}")
    return gaps
