"""Call arity against local definitions (P0 Step 7.2; TEST support, stdlib ``ast`` only).

``call_arity`` resolves each call through the caller's per-scope aliases and from-imports (``_contract_audit``) to
a local ``def``, following ``from … import`` re-exports, and reports too many positionals or a keyword the
signature lacks. ``*args``/``**kwargs`` definitions and starred calls are skipped; class constructors are not
checked (dataclasses may define their own ``__init__``). Adapted from report A's ``sigcheck.py``.
"""
from __future__ import annotations

import ast
from pathlib import Path

from _contract_audit import PRODUCER, Finding, _files, _module_level, _resolve, _scopes, module_index, tree_of


def _definition(module: str, name: str, index: dict, depth: int = 0) -> ast.AST | None:
    """The FunctionDef that ``module.name`` is, following ``from … import`` re-exports (a class gives None)."""
    if module not in index or depth > 5:
        return None
    for node in _module_level(tree_of(index[module]).body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return None if isinstance(node, ast.ClassDef) else node
        source = _reexport(node, name)
        if source is not None:
            return _definition(*source, index, depth + 1)
    return None


def _reexport(node: ast.AST, name: str) -> tuple[str, str] | None:
    """(module, original name) when ``node`` is ``from module import original [as name]``."""
    if not isinstance(node, ast.ImportFrom) or node.level:
        return None
    return next(((node.module or '', a.name) for a in node.names if (a.asname or a.name) == name), None)


def _arity(function: ast.AST, call: ast.Call) -> str | None:
    """Too many positionals or an unknown keyword (``*args``/``**kwargs`` and starred calls are skipped)."""
    spec = function.args
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(k.arg is None for k in call.keywords):
        return None
    params = [a.arg for a in spec.posonlyargs + spec.args]
    if len(call.args) > len(params) and spec.vararg is None:
        return f'{len(call.args)} positional > {len(params)} parameters'
    known = set(params[len(spec.posonlyargs):]) | {a.arg for a in spec.kwonlyargs}
    unknown = [k.arg for k in call.keywords if k.arg not in known] if spec.kwarg is None else []
    return f'unknown keyword {unknown}' if unknown else None


def call_arity(root: Path = PRODUCER, skip: tuple[str, ...] = ()) -> list[Finding]:
    """Calls resolved through an alias or a from-import to a local ``def`` that do not fit its signature."""
    index, found = module_index(root), []
    for path, rel, own in _files(root, skip):
        scopes = _scopes(path, index, own)
        calls = [node for node in ast.walk(tree_of(path)) if isinstance(node, ast.Call)]
        found += [row for row in (_check_call(node, (path, rel, scopes), index) for node in calls) if row]
    return sorted(set(found), key=Finding.key)


def _call_target(node: ast.Call, path: Path, scopes: dict) -> tuple[str, str] | None:
    """(module, name) a call resolves to through the caller's scopes, or None."""
    function = node.func
    if isinstance(function, ast.Name):
        resolved = _resolve(function.id, node, path, scopes)
        return resolved[1] if resolved and resolved[0] == 'name' else None
    if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
        resolved = _resolve(function.value.id, node, path, scopes)
        return (resolved[1], function.attr) if resolved and resolved[0] == 'module' else None
    return None


def _check_call(node: ast.Call, where: tuple, index: dict) -> Finding | None:
    """A finding when the call does not fit the local def it resolves to."""
    path, rel, scopes = where
    target = _call_target(node, path, scopes)
    definition = _definition(*target, index) if target else None
    problem = _arity(definition, node) if definition is not None else None
    return Finding(rel, node.lineno, f'{target[0]}.{target[1]}: {problem}') if problem else None
