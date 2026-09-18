"""Static local-import closure helper for frozen build catalogs."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCER_ROOT = REPO_ROOT / "scripts" / "producer"


def _repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _module_path(name: str) -> Path | None:
    if not name:
        return None
    base = PRODUCER_ROOT.joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _module_names(path: Path) -> tuple[str, ...]:
    relative = path.relative_to(PRODUCER_ROOT)
    package = list(relative.parts[:-1])
    names = []
    tree = ast.parse(path.read_bytes(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            keep = len(package) - node.level + 1
            prefix = package[:keep]
            module = ".".join((*prefix, *((node.module or "").split("."))))
        else:
            module = node.module or ""
        names.append(module)
        names.extend(
            ".".join(part for part in (module, alias.name) if part)
            for alias in node.names
        )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "run_module" or not node.args:
            continue
        value = getattr(node.args[0], "value", None)
        if type(value) is str:
            names.append(value)
    return tuple(names)


def _package_initializers(path: Path) -> tuple[Path, ...]:
    parents = []
    current = path.parent
    while current != PRODUCER_ROOT:
        candidate = current / "__init__.py"
        if candidate.is_file():
            parents.append(candidate)
        current = current.parent
    return tuple(parents)


def local_import_closure(entry_paths: tuple[str, ...]) -> frozenset[str]:
    """Resolve every statically named local import from exact entry paths."""
    pending = [REPO_ROOT / relative for relative in entry_paths]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        if not path.is_file():
            raise AssertionError(f"build catalog path is missing: {path}")
        seen.add(path)
        if path.suffix != ".py":
            continue
        pending.extend(_package_initializers(path))
        pending.extend(
            resolved
            for name in _module_names(path)
            if (resolved := _module_path(name)) is not None
        )
    return frozenset(_repo_relative(path) for path in seen)


def dynamic_import_calls(paths: frozenset[str]) -> tuple[str, ...]:
    """Return local modules containing unresolved dynamic import calls."""
    found = []
    for relative in paths:
        path = REPO_ROOT / relative
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None)
            attribute = getattr(node.func, "attr", None)
            if name == "__import__" or attribute == "import_module":
                found.append(f"{relative}:{node.lineno}")
                continue
            if attribute != "run_module":
                continue
            value = getattr(node.args[0], "value", None) if node.args else None
            target = _module_path(value) if type(value) is str else None
            if target is None or _repo_relative(target) not in paths:
                found.append(f"{relative}:{node.lineno}")
    return tuple(sorted(found))
