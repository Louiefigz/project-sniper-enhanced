"""Transitive import tripwire for the headless deterministic-MP4 package."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
HEADLESS_DIR = PRODUCER_DIR / "headless"
FORBIDDEN_PARTS = frozenset(
    {"app", "components", "contexts", "gui", "palmier", "pages"}
)
FORBIDDEN_PREFIXES = ("src.app", "src.components", "youtube_automation_ui")


def _module_path(module: str) -> Path | None:
    """Resolve one import name only when it belongs to producer source."""
    parts = module.split(".")
    file_path = PRODUCER_DIR.joinpath(*parts).with_suffix(".py")
    if file_path.is_file():
        return file_path
    package_path = PRODUCER_DIR.joinpath(*parts, "__init__.py")
    return package_path if package_path.is_file() else None


def _module_name(path: Path) -> str:
    """Return the producer-relative import name for one Python source."""
    relative = path.relative_to(PRODUCER_DIR).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _relative_module(
    current: str, node: ast.ImportFrom, is_package: bool
) -> str:
    """Resolve a relative import to its absolute producer module name."""
    package = current.split(".") if is_package else current.split(".")[:-1]
    keep = len(package) - (node.level - 1)
    base = package[:keep]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _imports(path: Path) -> tuple[str, ...]:
    """Extract static imports and reject dynamic import calls."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    current = _module_name(path)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = (
                _relative_module(current, node, path.name == "__init__.py")
                if node.level
                else (node.module or "")
            )
            if base:
                modules.add(base)
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base else alias.name
                if _module_path(candidate) is not None:
                    modules.add(candidate)
        elif isinstance(node, ast.Call) and _dynamic_import(node):
            raise AssertionError(
                f"dynamic import escapes static proof: {path}"
            )
    return tuple(sorted(modules))


def _dynamic_import(node: ast.Call) -> bool:
    """Return whether a call can import modules outside the static graph."""
    if isinstance(node.func, ast.Name):
        return node.func.id == "__import__"
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
    )


def _forbidden(module: str) -> bool:
    """Recognize GUI/Palmier namespaces without matching policy field names."""
    parts = frozenset(module.casefold().replace("-", "_").split("."))
    lowered = module.casefold()
    return bool(parts & FORBIDDEN_PARTS) or lowered.startswith(
        FORBIDDEN_PREFIXES
    )


def _reachable_sources() -> tuple[Path, ...]:
    """Walk every local import reachable from every headless module."""
    pending = list(sorted(HEADLESS_DIR.glob("*.py")))
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        for module in _imports(path):
            if _forbidden(module):
                raise AssertionError(
                    f"forbidden headless import: {module} in {path}"
                )
            target = _module_path(module)
            if target is not None and target not in visited:
                pending.append(target)
    return tuple(sorted(visited))


class HeadlessImportBoundaryTests(unittest.TestCase):
    def test_all_headless_modules_keep_gui_and_palmier_unreachable(
        self,
    ) -> None:
        sources = _reachable_sources()
        self.assertTrue(sources)
        self.assertTrue(all(PRODUCER_DIR in path.parents for path in sources))
        self.assertFalse(
            any(
                "palmier" in path.relative_to(PRODUCER_DIR).parts
                for path in sources
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
