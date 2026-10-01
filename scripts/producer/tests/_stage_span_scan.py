"""The AST scan behind test_native_budget_stage_catalog (M-109, P3b-12): every span name the producer code writes.

``scan()`` parses every non-test ``.py`` under ``scripts/producer`` and finds each call of a span-writing
``stage_timing`` function (``SPAN_FUNCTIONS``), by name or as an attribute. A stage argument must be a literal, an
f-string with a literal head (a prefix), or a local assigned once from literals; anything else, a renamed or star
import, or a span function used as a value is recorded in ``problems``. In ``stage_timing.py`` a span function
forwarding its own ``stage`` parameter is the API itself. Split from the test module (X231, X-R7) without change.
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


def assigned_once(name: str, scope: ast.AST) -> ast.expr | None:
    """The value of a local bound exactly once in ``scope``, by a plain assignment, and not a parameter."""
    stores = [node for node in ast.walk(scope) if isinstance(node, ast.Name) and node.id == name
              and isinstance(node.ctx, ast.Store)]
    values = [node.value for node in ast.walk(scope) if isinstance(node, ast.Assign) and node.targets == stores]
    return values[0] if len(stores) == 1 and len(values) == 1 and name not in parameters(scope) else None


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
        """A renamed or star import of a span function would hide its calls from the scan."""
        if node.module == 'stage_timing' and any(item.name == '*' or (item.name in SPAN_FUNCTIONS and item.asname)
                                                 for item in node.names):
            self.problems.append(f'{self.module}:{node.lineno} renamed or star import of a span function')

    def visit_Call(self, node: ast.Call) -> None:
        """A span call by name or attribute; the callee itself is not a value use."""
        callee = node.func
        name = callee.id if isinstance(callee, ast.Name) else getattr(callee, 'attr', None)
        if name in SPAN_FUNCTIONS:
            self.span_call(node, name)
        if isinstance(callee, ast.Attribute):
            self.visit(callee.value)
        elif not isinstance(callee, ast.Name):
            self.visit(callee)
        for item in (*node.args, *node.keywords):
            self.visit(item)

    def visit_Name(self, node: ast.Name) -> None:
        """A span function passed around as a value cannot be followed."""
        if node.id in SPAN_FUNCTIONS and isinstance(node.ctx, ast.Load):
            self.problems.append(f'{self.module}:{node.lineno} {node.id} used as a value')

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """``module.span_function`` passed around as a value cannot be followed either."""
        if node.attr in SPAN_FUNCTIONS:
            self.problems.append(f'{self.module}:{node.lineno} {node.attr} used as a value')
        self.generic_visit(node)

    def forwards(self, argument: ast.expr) -> bool:
        """Inside stage_timing.py, a span function passing its own ``stage`` parameter on is the API itself."""
        return self.module == API_MODULE and isinstance(argument, ast.Name) and argument.id == 'stage' and any(
            isinstance(scope, FUNCTIONS) and scope.name in SPAN_FUNCTIONS and 'stage' in parameters(scope)
            for scope in self.stack)

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
    """Every span call in the producer code (a module that never names a span function cannot call one)."""
    calls = SpanCalls()
    for path in producer_modules(root):
        text = path.read_text(encoding='utf-8')
        if any(name in text for name in SPAN_FUNCTIONS):
            calls.read(path.relative_to(root).as_posix(), text)
    return calls
