"""Record-field contracts and ESM named imports (P0 Step 7.2; TEST support, stdlib only).

``record_keys`` / ``event_keys`` / ``literal_keys`` collect the literal keys writers put into a curated record
contract (``tests/fixtures/record_contracts.json``); ``contract_problems`` names every required key no writer
writes. ``esm_missing`` is the ``mjs.py`` rule. Limits as in ``_contract_audit``: the table is curated, JSON written
by TypeScript or JavaScript is outside it, and keys written through a helper under another name are not seen.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from _contract_audit import PRODUCER, SKIPPED_DIRS, Finding, tree_of


def record_keys(paths: list[Path], owners: tuple[str, ...]) -> set[str]:
    """Literal keys written into a record named by one of ``owners`` (e.g. ``self.result``)."""
    return {key for path in paths for node in ast.walk(tree_of(path)) for key in _written_keys(node, owners)}


def _written_keys(node: ast.AST, owners: tuple[str, ...]) -> set[str]:
    """Keys one statement writes: ``X = {…}``, ``X[k] = …``, ``X.update(…)``, ``X.setdefault(k, …)``."""
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) \
            and any(ast.unparse(target) in owners for target in node.targets):
        return _dict_keys(node.value)
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) and ast.unparse(node.value) in owners \
            and isinstance(node.slice, ast.Constant):
        return {node.slice.value}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and ast.unparse(node.func.value) in owners and node.func.attr in ('update', 'setdefault'):
        return _call_keys(node)
    return set()


def _call_keys(node: ast.Call) -> set[str]:
    """Keyword and literal keys of an ``update``/``setdefault`` call."""
    keys = {k.arg for k in node.keywords if k.arg}
    first = node.args[0] if node.args else None
    if isinstance(first, ast.Dict):
        keys |= _dict_keys(first)
    elif isinstance(first, ast.Constant) and node.func.attr == 'setdefault':
        keys.add(first.value)
    return keys


def _dict_keys(node: ast.Dict) -> set:
    """Literal keys of one dict display."""
    return {k.value for k in node.keys if isinstance(k, ast.Constant)}


def event_keys(paths: list[Path], event: str) -> set[str]:
    """Union of keys of every dict literal whose ``'event'`` value is ``event``."""
    return {key for path in paths for node in ast.walk(tree_of(path)) if isinstance(node, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == 'event' and isinstance(v, ast.Constant)
                    and v.value == event for k, v in zip(node.keys, node.values)) for key in _dict_keys(node)}


def literal_keys(paths: list[Path], anchor: str) -> set[str]:
    """Union of keys of every dict literal that has the key ``anchor`` (a record's own identifying field)."""
    return {key for path in paths for node in ast.walk(tree_of(path))
            if isinstance(node, ast.Dict) and anchor in _dict_keys(node) for key in _dict_keys(node)}


def contract_problems(rows: list[dict], root: Path = PRODUCER) -> list[str]:
    """For each curated contract, the required keys its writers never write."""
    problems = []
    for row in rows:
        paths = [root / name for name in row['writers']]
        if 'owners' in row:
            written = record_keys(paths, tuple(row['owners']))
        elif 'event' in row:
            written = event_keys(paths, row['event'])
        else:
            written = literal_keys(paths, row['literal'])
        missing = sorted(set(row['required']) - written)
        if missing:
            problems.append(f"{row['name']}: {', '.join(row['writers'])} never write {missing} "
                            f"(read by {', '.join(row['readers'])})")
    return problems


def load_contracts(root: Path = PRODUCER) -> list[dict]:
    """The curated record contract table."""
    return json.loads((root / 'tests/fixtures/record_contracts.json').read_text())['contracts']


_IMPORT = re.compile(r'import\s*\{([^}]*)\}\s*from\s*[\'"](\.[^\'"]+)[\'"]', re.S)


def _exports(path: Path) -> tuple[set[str], bool]:
    """Named exports of an ESM file and whether it re-exports ``*``."""
    text = path.read_text(encoding='utf-8')
    names = set(re.findall(r'export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)', text))
    for group in re.findall(r'export\s*\{([^}]*)\}', text):
        names |= {part.split(' as ')[-1].strip() for part in group.split(',') if part.strip()}
    for group in re.findall(r'export\s+(?:const|let)\s*\{([^}]*)\}', text):
        names |= {part.split(':')[-1].strip() for part in group.split(',') if part.strip()}
    return names, 'export *' in text


def esm_missing(root: Path) -> list[Finding]:
    """Named imports of a relative ``.mjs``/``.js`` module that the module does not export (the mjs.py rule)."""
    found = []
    for path in sorted(p for p in root.rglob('*.mjs') if not SKIPPED_DIRS & set(p.parts)):
        for names, source in _IMPORT.findall(path.read_text(encoding='utf-8')):
            found += _import_problems(root, path, names, source)
    return found


def _import_problems(root: Path, path: Path, names: str, source: str) -> list[Finding]:
    """What one ``import {…} from './x.mjs'`` asks for that ``x`` lacks (a missing file is one finding)."""
    where, target = str(path.relative_to(root)), (path.parent / source).resolve()
    if not target.exists():
        return [Finding(where, 0, f'missing file {source}')]
    exported, star = _exports(target) if target.suffix in ('.mjs', '.js') else (set(), True)
    wanted = [name.split(' as ')[0].strip() for name in names.split(',')]
    return [Finding(where, 0, f'{name} is not exported by {source}') for name in wanted
            if name and not star and name not in exported]
