"""Engineering standards checker for Python files (MASTER-PLAN G11; P0 Step 7.0). Static only: parses, never imports.

Rules, per file: at most 300 physical lines unless the file is named with ``--data-catalog`` (data catalogs are
exempt by the house rule; nothing is guessed). Per function or method: at most 50 lines (``def`` line to last
line, docstring included), at most 4 parameters (``self``/``cls`` excluded; ``*args``/``**kwargs`` count), nesting
of at most 2 compound statements (``if/for/while/try/with/match``; an ``elif`` stays at its ``if``'s level; a
nested function starts again at 0), a return annotation and an annotation on every parameter, and a docstring.
Every class needs a docstring.

  standards_check.py [--data-catalog PATH]... [--baseline FILE]... FILE...
  standards_check.py --write-baseline FILE [--data-catalog PATH]... FILE...

With ``--baseline`` a violation already recorded there is reported as ``baseline`` and does not fail, unless it
got worse (a longer file or function, more parameters, deeper nesting). Keys are path + rule + qualified name,
so a line shift is not a new violation. Exit 0 when no new violation exists, 1 otherwise. What it cannot see:
semantic quality, docstring *style* (Google sections are not parsed), and TypeScript (``ts_standards_check.cjs``).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

FILE_LINES, FUNCTION_LINES, PARAMETERS, NESTING = 300, 50, 4, 2
COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)
if hasattr(ast, 'TryStar'):
    COMPOUND = (*COMPOUND, ast.TryStar)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


@dataclass(frozen=True)
class Violation:
    """One rule a file or function breaks, with the measured value."""

    path: str
    line: int
    rule: str
    name: str
    value: int

    def key(self) -> str:
        """Stable identity across line shifts."""
        return f'{self.path}::{self.rule}::{self.name}'

    def text(self) -> str:
        """One printable line."""
        return f'{self.path}:{self.line} {self.rule} {self.name} ({self.value})'


def depth(node: ast.AST, level: int = 0) -> int:
    """Deepest compound-statement nesting under ``node``; ``elif`` does not add a level; scopes restart."""
    deepest = level
    for child in ast.iter_child_nodes(node):
        if isinstance(child, SCOPES):
            continue
        is_elif = isinstance(node, ast.If) and isinstance(child, ast.If) and node.orelse == [child]
        inner = level + 1 if isinstance(child, COMPOUND) and not is_elif else level
        deepest = max(deepest, depth(child, inner))
    return deepest


def parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    """Named parameters, ``self``/``cls`` first-positional excluded; ``*args``/``**kwargs`` included."""
    args = node.args
    rows = [*args.posonlyargs, *args.args, *args.kwonlyargs, *[a for a in (args.vararg, args.kwarg) if a]]
    if rows and rows[0] in (args.posonlyargs + args.args)[:1] and rows[0].arg in ('self', 'cls'):
        rows = rows[1:]
    return rows


def function_rows(path: str, node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> list[Violation]:
    """Every rule one function breaks."""
    rows = []
    length = node.end_lineno - node.lineno + 1
    params = parameters(node)
    nesting = max((depth(statement, 1 if isinstance(statement, COMPOUND) else 0) for statement in node.body), default=0)
    checks = (('function-lines', length, length > FUNCTION_LINES), ('parameters', len(params), len(params) > PARAMETERS),
              ('nesting', nesting, nesting > NESTING), ('return-hint', 0, node.returns is None),
              ('parameter-hints', sum(p.annotation is None for p in params), any(p.annotation is None for p in params)),
              ('docstring', 0, ast.get_docstring(node) is None))
    for rule, value, broken in checks:
        if broken:
            rows.append(Violation(path, node.lineno, rule, name, value))
    return rows


def node_rows(path: str, node: ast.stmt, prefix: str) -> list[Violation]:
    """The violations of one function or class itself (its nested definitions are walked separately)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return function_rows(path, node, prefix + node.name)
    missing = ast.get_docstring(node) is None
    return [Violation(path, node.lineno, 'docstring', prefix + node.name, 0)] if missing else []


def walk(path: str, body: list[ast.stmt], prefix: str = '') -> list[Violation]:
    """Visit functions and classes at any depth, with qualified names."""
    rows = []
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rows += node_rows(path, node, prefix) + walk(path, node.body, f'{prefix}{node.name}.')
    return rows


def check(path: Path, catalogs: set[str]) -> list[Violation]:
    """Every violation of one file."""
    text = path.read_text(encoding='utf-8')
    name = str(path)
    lines = len(text.splitlines())
    rows = [] if name in catalogs or lines <= FILE_LINES else [Violation(name, 1, 'file-lines', '<file>', lines)]
    return rows + walk(name, ast.parse(text, name).body)


def compare(rows: list[Violation], baseline: dict[str, int]) -> tuple[list[Violation], list[Violation]]:
    """(new or worse, already recorded and not worse)."""
    new, known = [], []
    for row in rows:
        recorded = baseline.get(row.key())
        (known if recorded is not None and row.value <= recorded else new).append(row)
    return new, known


def merged(files: list[Path]) -> dict[str, int]:
    """Union of several baseline files; a key in two of them keeps the larger recorded value."""
    rows: dict[str, int] = {}
    for file in files:
        for key, value in json.loads(file.read_text()).items():
            rows[key] = max(value, rows.get(key, value))
    return rows


def main(argv: list[str]) -> int:
    """Check the named files; print one line per violation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--data-catalog', action='append', default=[], type=Path)
    parser.add_argument('--baseline', action='append', default=[], type=Path, help='repeatable; values merge (max)')
    parser.add_argument('--write-baseline', type=Path)
    args = parser.parse_args(argv)
    catalogs = {str(path) for path in args.data_catalog}
    rows = [row for file in args.files for row in check(file, catalogs)]
    if args.write_baseline:
        args.write_baseline.write_text(json.dumps({row.key(): row.value for row in rows}, indent=0, sort_keys=True))
        print(f'baseline written: {len(rows)} recorded violation(s)')
        return 0
    new, known = compare(rows, merged(args.baseline))
    for row in known:
        print('baseline', row.text())
    for row in new:
        print('VIOLATION', row.text())
    print(f'standards: {len(new)} new, {len(known)} recorded in the baseline, {len(args.files)} file(s)')
    return 1 if new else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
