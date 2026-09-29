"""Static cross-module contract audit over scripts/producer (P0 Step 7.2; TEST support, stdlib ``ast`` only).

Report A §4 found every mixed-version defect where import and arity checks cannot see: a module attribute a caller
uses that its module lacks (M1), and a record field a reader needs that no writer writes (M2, M3, M8). This module
finds both statically:

- ``missing_attributes``: ``alias.attr`` and ``getattr(alias, 'attr')`` uses, ``from mod import name`` and
  ``import pkg.mod`` of local modules, whose target does not define the name or submodule;
- call arity (a local ``def`` called with too many positionals or a keyword it lacks): ``_contract_calls.py``;
- record contracts and ESM named imports: ``_contract_records.py``.

Limits. Record contracts are only as complete as the curated table. JSON written by TypeScript or JavaScript is
outside this audit. Data flow through helper functions is not followed: a key written by a helper that receives the
record under another name is not seen. Aliases resolve per function scope (a local assignment shadows a module
alias), not per branch. Class constructors are not arity-checked. ``getattr`` with a default is a presence probe
and is skipped. A module that assigns into ``globals()``, uses module-level ``setattr`` or defines a module
``__getattr__`` is reported as dynamic, never passed.
"""
from __future__ import annotations

import ast
import functools
from dataclasses import dataclass
from pathlib import Path

PRODUCER = Path(__file__).resolve().parents[1]
SKIPPED_DIRS = {'node_modules', '__pycache__', '.venv', 'venv'}
MODULE_ATTRIBUTES = {'__file__', '__doc__', '__name__', '__path__', '__spec__', '__loader__', '__dict__',
                     '__package__'}  # every module object has these
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


@dataclass(frozen=True)
class Finding:
    """One audit result: ``file:line`` and what is missing or wrong."""

    file: str
    line: int
    detail: str

    def key(self) -> str:
        """Stable identity used by the tests' KNOWN tables."""
        return f'{self.file}:{self.line} {self.detail}'


def module_index(root: Path = PRODUCER) -> dict[str, Path]:
    """Importable module name -> file, for the ``PYTHONPATH=.:tests`` layout the suite uses."""
    index: dict[str, Path] = {}
    for base in (root, root / 'tests'):
        for path in sorted(base.rglob('*.py')):
            index.setdefault(_module_name(root, base, path), path)
    index.pop('', None)
    return index


def _module_name(root: Path, base: Path, path: Path) -> str:
    """Dotted name of ``path`` under ``base`` ('' for a skipped directory or a producer-root view of tests/)."""
    parts = path.relative_to(base).with_suffix('').parts
    if SKIPPED_DIRS & set(parts) or (base == root and parts[0] == 'tests'):
        return ''
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


@functools.lru_cache(maxsize=None)
def tree_of(path: Path) -> ast.Module:
    """Parse once per process."""
    return ast.parse(path.read_text(encoding='utf-8'), str(path))


@functools.lru_cache(maxsize=None)
def top_level_names(path: Path) -> set[str] | None:
    """Names a module defines at import time (including under module-level if/try), or None when dynamic."""
    statements = _module_level(tree_of(path).body)
    if any(_writes_namespace(node, path) for node in ast.walk(tree_of(path))) \
            or any(isinstance(node, ast.FunctionDef) and node.name == '__getattr__' for node in statements):
        return None
    return set().union(*(_bound_names(node) for node in statements))


def _writes_namespace(node: ast.AST, path: Path) -> bool:
    """``globals()[…]`` anywhere, or ``setattr(…)`` at module level: the module's names are not static."""
    if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'setattr':
        return _nearest_function(node, _parents(path)) is None
    return isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call) \
        and getattr(node.value.func, 'id', '') == 'globals'


def _bound_names(node: ast.stmt) -> set[str]:
    """Names one import-time statement binds (defs, classes, imports, assignment/loop/with targets)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(alias.asname or alias.name).split('.')[0] for alias in node.names}
    targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, 'target', None)]
    targets += [item.optional_vars for item in getattr(node, 'items', [])]
    return {n.id for target in targets if target is not None for n in ast.walk(target) if isinstance(n, ast.Name)}


def _module_level(body: list[ast.stmt]) -> list[ast.stmt]:
    """Statements that run at import: the body plus every if/try/with branch, never function bodies."""
    out: list[ast.stmt] = []
    for node in body:
        out += [node, *_module_level(_branches(node))]
    return out


def _branches(node: ast.stmt) -> list[ast.stmt]:
    """The nested statements of an if/try/with/for/while (empty for anything else)."""
    if not isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
        return []
    branches = [node.body, getattr(node, 'orelse', []), getattr(node, 'finalbody', [])]
    branches += [handler.body for handler in getattr(node, 'handlers', [])]
    return [child for branch in branches for child in branch]


@functools.lru_cache(maxsize=None)
def _parents(path: Path) -> dict[ast.AST, ast.AST]:
    """Child -> parent map of one module."""
    return {child: node for node in ast.walk(tree_of(path)) for child in ast.iter_child_nodes(node)}


def _nearest_function(node: ast.AST, parents: dict) -> ast.AST | None:
    """The innermost function or lambda around a node, or None at module level."""
    node = parents.get(node)
    while node is not None and not isinstance(node, FUNCTIONS):
        node = parents.get(node)
    return node


def _absolute(module: str | None, level: int, own: str, is_package: bool) -> str:
    """Resolve a (possibly relative) ``from`` target against the importing module's own name."""
    if not level:
        return module or ''
    package = own.split('.') if is_package else own.split('.')[:-1]
    package = package[:len(package) - (level - 1)]
    return '.'.join(package + ([module] if module else []))


@dataclass
class Scope:
    """Local aliases (name -> module), from-imported names (name -> (module, name)) and names bound locally."""

    modules: dict
    names: dict
    bound: set


def module_aliases(nodes: list[ast.AST], index: dict, own: tuple[str, bool]) -> Scope:
    """What the import statements among ``nodes`` bind to local modules (``import X as m``, ``from P import m``)."""
    scope = Scope({}, {}, set())
    for node in nodes:
        if isinstance(node, ast.Import):
            _import_aliases(node, index, scope)
        elif isinstance(node, ast.ImportFrom):
            _from_aliases(node, (index, own), scope)
    return scope


def _import_aliases(node: ast.Import, index: dict, scope: Scope) -> None:
    """``import a.b`` binds ``a``; ``import a.b as m`` binds ``m`` to ``a.b`` (local modules only)."""
    for alias in node.names:
        top = alias.name.split('.')[0]
        if top in index or alias.name in index:
            scope.modules[alias.asname or top] = alias.name if alias.asname else top


def _from_aliases(node: ast.ImportFrom, context: tuple, scope: Scope) -> None:
    """``from P import mod`` binds a module; ``from P import name`` records the name (local modules only)."""
    index, own = context
    target = _absolute(node.module, node.level, *own)
    for alias in node.names:
        local = alias.asname or alias.name
        if f'{target}.{alias.name}' in index:
            scope.modules[local] = f'{target}.{alias.name}'
        elif target in index and alias.name != '*':
            scope.names[local] = (target, alias.name)


def _scopes(path: Path, index: dict, own: tuple[str, bool]) -> dict[ast.AST | None, Scope]:
    """Scope per function (None: the module) with the names each binds, so a local shadows a module alias."""
    parents, tree = _parents(path), tree_of(path)
    grouped: dict[ast.AST | None, list[ast.AST]] = {None: []}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Name, ast.arg)) or isinstance(node, FUNCTIONS):
            grouped.setdefault(_nearest_function(node, parents), []).append(node)
    scopes = {}
    for owner, nodes in grouped.items():
        scope = module_aliases(nodes, index, own)
        if owner is not None:
            scope.bound = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            scope.bound |= {n.arg for n in nodes if isinstance(n, ast.arg)}
        scopes[owner] = scope
    return scopes


def _resolve(name: str, node: ast.AST, path: Path, scopes: dict) -> tuple[str, object] | None:
    """('module', name) or ('name', (module, attr)) for a Name at ``node``, innermost scope first."""
    function = _nearest_function(node, _parents(path))
    while True:
        scope = scopes.get(function) or Scope({}, {}, set())
        if name in scope.modules:
            return 'module', scope.modules[name]
        if name in scope.names:
            return 'name', scope.names[name]
        if function is None or name in scope.bound:
            return None
        function = _nearest_function(function, _parents(path))


def attribute_uses(path: Path, index: dict, own: tuple[str, bool]) -> list[tuple[int, str, str]]:
    """(line, module, attribute) for every ``alias.attr`` load and ``getattr(alias, 'attr')`` without default.

    A name the same file probes with ``hasattr(alias, 'attr')`` is a guarded optional use and is skipped.
    """
    scopes, uses = _scopes(path, index, own), []
    probed = {(n.args[0].id, n.args[1].value) for n in ast.walk(tree_of(path)) if isinstance(n, ast.Call)
              and getattr(n.func, 'id', '') == 'hasattr' and len(n.args) == 2 and isinstance(n.args[0], ast.Name)
              and isinstance(n.args[1], ast.Constant)}
    for node in ast.walk(tree_of(path)):
        base, attr = None, None
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name):
            base, attr = node.value, node.attr
        elif isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'getattr' and len(node.args) == 2 \
                and isinstance(node.args[0], ast.Name) and isinstance(node.args[1], ast.Constant):
            base, attr = node.args[0], node.args[1].value
        if base is None or (base.id, attr) in probed:
            continue
        resolved = _resolve(base.id, node, path, scopes)
        if resolved and resolved[0] == 'module':
            uses.append((node.lineno, resolved[1], attr))
    return uses


def _files(root: Path, skip: tuple[str, ...]) -> list[tuple[Path, str, tuple[str, bool]]]:
    """(file, repo-relative name, (module name, is package)) of every audited module."""
    rows = []
    for name, path in module_index(root).items():
        rel = str(path.relative_to(root))
        if not rel.startswith(skip):
            rows.append((path, rel, (name, path.name == '__init__.py')))
    return rows


def missing_attributes(root: Path = PRODUCER, skip: tuple[str, ...] = ()) -> list[Finding]:
    """Uses of a local module's attribute, name or submodule that the module does not define."""
    index, found = module_index(root), []
    for path, rel, own in _files(root, skip):
        checks = attribute_uses(path, index, own) + [row for node in ast.walk(tree_of(path))
                                                      for row in _import_checks(node, index, own)]
        found += [finding for finding in (_missing(rel, check, index) for check in checks) if finding]
    return sorted(set(found), key=Finding.key)


def _import_checks(node: ast.AST, index: dict, own: tuple[str, bool]) -> list[tuple[int, str, str]]:
    """(line, module, name) that ``from local import name`` and ``import local.pkg.mod`` require."""
    if isinstance(node, ast.ImportFrom):
        target = _absolute(node.module, node.level, *own)
        return [(node.lineno, target, a.name) for a in node.names if target in index and a.name != '*']
    if isinstance(node, ast.Import):
        return [(node.lineno, '.'.join(a.name.split('.')[:-1]), a.name.split('.')[-1])
                for a in node.names if '.' in a.name and a.name.split('.')[0] in index]
    return []


def _missing(rel: str, check: tuple[int, str, str], index: dict) -> Finding | None:
    """A finding when ``module`` does not define ``attr`` (or cannot be read statically), else None."""
    line, module, attr = check
    names = top_level_names(index[module]) if module in index else set()
    if names is None:
        return Finding(rel, line, f'{module} is dynamic (globals/setattr/__getattr__)')
    if attr in names | MODULE_ATTRIBUTES or f'{module}.{attr}' in index:
        return None
    return Finding(rel, line, f'{module}.{attr} is not defined')
