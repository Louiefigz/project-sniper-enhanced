"""The AST scan behind test_native_budget_stage_catalog (M-109, P3b-12): every span name the producer code writes.

``scan()`` parses every non-test ``.py`` under ``scripts/producer`` and finds each call of a span-writing
``stage_timing`` function (``SPAN_FUNCTIONS``), by name or as an attribute. A stage argument must be a literal, an
f-string with a literal head (a prefix), or a name bound exactly once in its function, by a plain assignment from
literals. Recorded in ``problems`` instead (X231 X-R1): anything else; a ``GUARDED`` function imported under another
name from any module (every importer re-exports it), star-imported from ``stage_timing``, used as a value or named in
a string (``getattr``); and a raw ``append_row`` row outside ``RAW_MODULES``. In ``stage_timing.py`` a span function
passing on its own ``stage`` parameter, bound nowhere else in it, is the API itself. Not seen: a guarded name built at
runtime, a row written to ``stage_timing.journal_path`` by hand, TypeScript ``timedStage`` and the markers CLI's
labels. Split from the test module (X231 X-R7).
"""
from __future__ import annotations

import ast
import functools
import os
from dataclasses import dataclass
from pathlib import Path

PRODUCER = Path(__file__).resolve().parents[1]
SPAN_FUNCTIONS = {'stage_span': 1, 'span_for_base': 1, 'child_span': 0, 'timed_stage': 0, 'journal_event': 1}
API_MODULE = 'stage_timing.py'
SKIPPED = {'tests', '__pycache__', 'node_modules', '.venv', 'venv'}
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
RAW_WRITER = 'append_row'                                  # writes a row with any stage name
RAW_MODULES = {API_MODULE, 'stage_timing_markers.py'}       # its only callers: the API and the markers CLI
GUARDED = {*SPAN_FUNCTIONS, RAW_WRITER}
NAME_FIELDS = {ast.arg: 'arg', ast.ExceptHandler: 'name', ast.FunctionDef: 'name', ast.AsyncFunctionDef: 'name',
               ast.ClassDef: 'name', ast.MatchAs: 'name', ast.MatchStar: 'name'}


@dataclass(frozen=True)
class Written:
    """One stage name a span call writes: a literal name, or an f-string's literal head (``prefix``)."""

    name: str
    prefix: bool
    module: str
    line: int


def stage_argument(call: ast.Call, position: int) -> ast.expr | None:
    """The call's ``stage`` keyword, else its positional argument at ``position``."""
    positional = call.args[position] if len(call.args) > position else None
    return next((item.value for item in call.keywords if item.arg == 'stage'), positional)


def parameters(function: ast.AST) -> set[str]:
    """The parameter names of a function node; none for a module."""
    if not isinstance(function, FUNCTIONS):
        return set()
    return {item.arg for item in ast.walk(function.args) if isinstance(item, ast.arg)}


def binds(node: ast.AST, name: str) -> bool:
    """Whether one node binds ``name``: a store or delete, a parameter (lambdas too), an except, match, import or
    global name, or a def or class."""
    if isinstance(node, ast.Name):
        return node.id == name and not isinstance(node.ctx, ast.Load)
    if isinstance(node, ast.alias):
        return (node.asname or node.name.split('.')[0]) == name
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return name in node.names
    field = NAME_FIELDS.get(type(node))
    return field is not None and getattr(node, field) == name


def bindings(name: str, scope: ast.AST) -> list[ast.AST]:
    """Every binding of ``name`` anywhere in ``scope``, nested functions and lambdas included."""
    return [node for node in ast.walk(scope) if binds(node, name)]


def assigned_once(name: str, scope: ast.AST) -> ast.expr | None:
    """The value of a name bound exactly once in ``scope``, by a plain assignment; any other binding (a parameter, a
    lambda argument, an except or import alias, a second store) makes it unresolvable (X231 R02)."""
    found = bindings(name, scope)
    values = [node.value for node in ast.walk(scope) if isinstance(node, ast.Assign) and node.targets == found]
    return values[0] if len(found) == 1 and len(values) == 1 else None


def stage_names(node: ast.expr | None, scope: ast.AST) -> list[tuple[str, bool]] | None:
    """Every (name, is_prefix) a stage argument can take, or None when the scan cannot tell."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [(node.value, False)]
    if isinstance(node, ast.JoinedStr):
        head = node.values[0] if node.values else None
        literal = isinstance(head, ast.Constant) and isinstance(head.value, str)
        return [(head.value, len(node.values) > 1)] if literal else None
    if isinstance(node, ast.IfExp):
        body, orelse = stage_names(node.body, scope), stage_names(node.orelse, scope)
        return None if body is None or orelse is None else body + orelse
    if isinstance(node, ast.Name):
        value = assigned_once(node.id, scope)
        return None if value is None else stage_names(value, scope)
    return None


class SpanCalls(ast.NodeVisitor):
    """The producer modules' span calls (``written``) and every call the scan could not follow (``problems``)."""

    def __init__(self) -> None:
        """No module read yet."""
        self.module, self.stack, self.written, self.problems = '', [], [], []

    def read(self, module: str, text: str) -> None:
        """Scan one module; a module that does not parse is a problem, not a skip."""
        try:
            tree = ast.parse(text, filename=module)
        except SyntaxError as error:
            self.problems.append(f'{module}: does not parse ({error.msg})')
            return
        self.module, self.stack = module, [tree]
        self.visit(tree)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Decorators and defaults belong to the enclosing scope; the body to the function's own."""
        for item in (*node.decorator_list, node.args, *([node.returns] if node.returns else [])):
            self.visit(item)
        self.stack.append(node)
        for item in node.body:
            self.visit(item)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """A guarded function imported under another name, from any module (X231 R05: every importer re-exports it),
        or a star import from stage_timing would hide its calls from the scan."""
        renamed = any(item.name in GUARDED and item.asname not in (None, item.name) for item in node.names)
        star = node.module == 'stage_timing' and any(item.name == '*' for item in node.names)
        if renamed or star:
            self.problems.append(f'{self.module}:{node.lineno} renamed or star import of a span function')

    def visit_Call(self, node: ast.Call) -> None:
        """A span call by name or attribute; the callee itself is not a value use."""
        callee = node.func
        name = callee.id if isinstance(callee, ast.Name) else getattr(callee, 'attr', None)
        if name in SPAN_FUNCTIONS:
            self.span_call(node, name)
        if name == RAW_WRITER and self.module not in RAW_MODULES:
            self.problems.append(f'{self.module}:{node.lineno} raw journal row ({RAW_WRITER}) outside the timing API')
        if isinstance(callee, ast.Attribute):
            self.visit(callee.value)
        elif not isinstance(callee, ast.Name):
            self.visit(callee)
        for item in (*node.args, *node.keywords):
            self.visit(item)

    def visit_Name(self, node: ast.Name) -> None:
        """A guarded function passed around as a value cannot be followed."""
        if node.id in GUARDED and isinstance(node.ctx, ast.Load):
            self.problems.append(f'{self.module}:{node.lineno} {node.id} used as a value')

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """``module.function`` passed around as a value cannot be followed either."""
        if node.attr in GUARDED:
            self.problems.append(f'{self.module}:{node.lineno} {node.attr} used as a value')
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """A guarded function named in a string, as ``getattr(stage_timing, 'stage_span')`` does (X231 R04)."""
        if isinstance(node.value, str) and node.value in GUARDED:
            self.problems.append(f'{self.module}:{node.lineno} {node.value} named in a string')

    def forwards(self, argument: ast.expr) -> bool:
        """In stage_timing.py, a span function passing on its own ``stage`` parameter is the API itself, provided
        nothing else in it binds ``stage`` (X231 R01: a rebound ``stage`` is resolved like any other name)."""
        if self.module != API_MODULE or not isinstance(argument, ast.Name) or argument.id != 'stage':
            return False
        owners = [scope for scope in self.stack
                  if isinstance(scope, FUNCTIONS) and scope.name in SPAN_FUNCTIONS and 'stage' in parameters(scope)]
        return len(owners) == 1 and len(bindings('stage', owners[0])) == 1

    def span_call(self, node: ast.Call, function: str) -> None:
        """Record the names one span call writes, or the reason the scan cannot tell."""
        argument = stage_argument(node, SPAN_FUNCTIONS[function])
        if argument is not None and self.forwards(argument):
            return
        names = stage_names(argument, self.stack[-1])
        if names is None:
            self.problems.append(f'{self.module}:{node.lineno} {function}: stage name not resolvable')
            return
        self.written.extend(Written(name, prefix, self.module, node.lineno) for name, prefix in names)


def producer_modules(root: Path) -> list[Path]:
    """Every non-test Python file under the producer folder (no tests, caches, virtualenvs or hidden folders)."""
    found = []
    for folder, children, files in os.walk(root):
        children[:] = sorted(name for name in children if name not in SKIPPED and not name.startswith('.'))
        found.extend(Path(folder, name) for name in sorted(files) if name.endswith('.py'))
    return found


@functools.cache
def scan(root: Path = PRODUCER) -> SpanCalls:
    """Every span call in the producer code (a module that never names a guarded function cannot call one)."""
    calls = SpanCalls()
    for path in producer_modules(root):
        text = path.read_text(encoding='utf-8')
        if any(name in text for name in GUARDED):
            calls.read(path.relative_to(root).as_posix(), text)
    return calls
