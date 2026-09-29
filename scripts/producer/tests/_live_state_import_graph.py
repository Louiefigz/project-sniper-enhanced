"""Static import analysis for the live-state coverage checks (test_live_state_coverage.py).

``ImportGraph`` follows local imports through the suite's search roots (tests/, scripts/producer,
scripts/). It keeps two edge sets per module: imports at any depth, and imports executed at
import time (module-level statements, including those inside module-level if/try/with blocks).
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PRODUCER = TESTS.parent
SEARCH = (TESTS, PRODUCER, PRODUCER.parent)
OWNERS = frozenset({'studio.native_budget_store', 'native_work_lease', 'native_work_qualification'})
ISOLATION = '_live_state_isolation'


def imports(path: Path, package: str) -> tuple[set[str], set[str]]:
    """(names imported at any depth, names imported by module-level statements) of one file."""
    found: tuple[set[str], set[str]] = (set(), set())
    _collect(ast.parse(path.read_text(), str(path)).body, package, True, found)
    return found


def _collect(body: list[ast.stmt], package: str, top: bool, found: tuple[set[str], set[str]]) -> None:
    """Walk statements only (imports are statements); def/class bodies are not module level."""
    for node in body:
        names = _names(node, package)
        found[0].update(names)
        if top:
            found[1].update(names)
        module_level = top and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for child in _child_bodies(node):
            _collect(child, package, module_level, found)


def _child_bodies(node: ast.stmt) -> list[list[ast.stmt]]:
    """The nested statement lists of a compound statement."""
    bodies = [getattr(node, name) for name in ('body', 'orelse', 'finalbody')
              if isinstance(getattr(node, name, None), list)]
    bodies += [handler.body for handler in getattr(node, 'handlers', [])]
    return bodies + [case.body for case in getattr(node, 'cases', [])]


def _names(node: ast.AST, package: str) -> set[str]:
    """Candidate module names one import statement loads (packages and from-imported submodules)."""
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if not isinstance(node, ast.ImportFrom):
        return set()
    base = node.module or ''
    if node.level:
        parts = package.split('.')[:len(package.split('.')) - node.level + 1]
        base = '.'.join(part for part in [*parts, node.module] if part)
    return {base} | {f'{base}.{alias.name}' for alias in node.names}


@functools.cache
def module_file(name: str) -> Path | None:
    """The source file for a local module name on the suite's search roots."""
    parts = name.split('.')
    for root in SEARCH:
        base = root.joinpath(*parts)
        for candidate in (base.with_suffix('.py'), base / '__init__.py'):
            if candidate.is_file():
                return candidate
    return None


class ImportGraph:
    """Local import edges (any depth, and module-level only) parsed once per file."""

    def __init__(self) -> None:
        """Start with an empty cache."""
        self.edges: dict[str, tuple[set[str], set[str]]] = {}

    def local(self, name: str) -> tuple[set[str], set[str]]:
        """The local modules (with their parent packages) that ``name`` imports."""
        if name not in self.edges:
            self.edges[name] = (set(), set())
            path = module_file(name)
            if path is not None:
                package = name if path.name == '__init__.py' else name.rpartition('.')[0]
                self.edges[name] = tuple(self._expand(found) for found in imports(path, package))
        return self.edges[name]

    @staticmethod
    def _expand(found: set[str]) -> set[str]:
        """Keep local modules and add the packages their import executes."""
        local = {name for name in found if name and module_file(name) is not None}
        return local | {'.'.join(name.split('.')[:depth]) for name in local
                        for depth in range(1, name.count('.') + 1)}

    def closure(self, name: str, top_only: bool) -> set[str]:
        """Every local module reached from ``name`` (module-level statements only when asked).

        The isolation module's own imports of the owners are not followed, so importing it
        never makes a module count as one that reaches the owners by itself.
        """
        seen, stack = set(), [name]
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(set() if current == ISOLATION else self.local(current)[1 if top_only else 0] - seen)
        return seen


DYNAMIC_IMPORTS = frozenset({'import_module', '__import__', 'run_path', 'run_module', 'spec_from_file_location'})


def dynamic_sites(path: Path) -> set[str]:
    """The dynamic-import calls and ``sys.executable`` uses (child launches) in one file."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Attribute) and node.attr == 'executable' \
                and isinstance(node.value, ast.Name) and node.value.id == 'sys':
            found.add('sys.executable')
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
        if name in DYNAMIC_IMPORTS:
            found.add(name)
    return found
