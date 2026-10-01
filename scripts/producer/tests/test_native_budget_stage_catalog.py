"""M-109 (P3b-12): the stage catalog classifies every span name the producer code writes, and names nothing else.

The scan parses every non-test ``.py`` under ``scripts/producer`` with ``ast`` and finds each call of a span-writing
``stage_timing`` function (``SPAN_FUNCTIONS``), by name or as an attribute. A stage argument must be a literal, an
f-string with a literal head (a prefix), or a local assigned once from literals (the Short worker's
``picture_stage``); anything else, a renamed or star import, or a span function used as a value is a scan problem.
In ``stage_timing.py`` a span function forwarding its own ``stage`` parameter is the API itself. P3b-12 requires
code -> catalog; this module adds catalog -> code: every catalogued name, prefix, module and clock field is written,
except ``PLANNED_STAGES``, which must not be. The scan cannot see TypeScript ``timedStage`` names, stage labels given
on the ``stage_timing.py`` command line, raw ``append_row`` rows or a span function reached through ``getattr``.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import ast
import functools
import os
import unittest
from dataclasses import dataclass
from pathlib import Path

from studio import native_budget_stage_catalog as catalog

PRODUCER = Path(__file__).resolve().parents[1]
SPAN_FUNCTIONS = {'stage_span': 1, 'span_for_base': 1, 'child_span': 0, 'timed_stage': 0, 'journal_event': 1}
API_MODULE = 'stage_timing.py'
SKIPPED = {'tests', '__pycache__', 'node_modules', '.venv', 'venv'}
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
CLOCK_MODULE = 'studio/production/queue_clock.py'
HANDOFF_MODULE = 'studio/production/queue_handoff.py'


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


def groups(item: Written) -> list[str]:
    """Every catalog group that claims one written name; exactly one must."""
    outside = catalog.OUTSIDE_LAUNCH_STAGES.get(item.module)
    if outside is not None:
        return ['outside'] if not item.prefix and item.name in outside else []
    found = [head for head in (*catalog.STAGE_PREFIX, *catalog.ENVELOPE_PREFIX) if item.name.startswith(head)]
    whole = (('category', catalog.STAGE_CATEGORY), ('wait', catalog.ADMISSION_WAIT_STAGES))
    return found + [group for group, names in whole if not item.prefix and item.name in names]


def returned_dict(relative: str, function: str) -> tuple[ast.FunctionDef, ast.Dict]:
    """A module-level function of a producer module, and the one dict literal it returns."""
    tree = ast.parse((PRODUCER / relative).read_text(encoding='utf-8'))
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function]
    returns = [node.value for body in found for node in ast.walk(body) if isinstance(node, ast.Return)]
    if len(found) != 1 or len(returns) != 1 or not isinstance(returns[0], ast.Dict):
        raise AssertionError(f'{relative}: {function} is not one module-level function returning one dict literal')
    return found[0], returns[0]


def constant_keys(node: ast.Dict) -> set[str]:
    """The string keys of a dict literal (``**`` splats have no key)."""
    return {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}


def added_fields() -> tuple[ast.FunctionDef, ast.Dict, set[str]]:
    """frozen_times, its returned dict, and the keys it adds beyond queue_clock.status's own."""
    function, frozen = returned_dict(HANDOFF_MODULE, 'frozen_times')
    return function, frozen, constant_keys(frozen) - constant_keys(returned_dict(CLOCK_MODULE, 'status')[1])


class StageCatalogShapeTests(unittest.TestCase):
    """The catalog is consistent with itself."""

    def test_categories_are_known_and_no_name_or_prefix_is_claimed_twice(self) -> None:
        """Mapped categories are CATEGORIES; groups are disjoint; no name falls under a prefix or prefix under one."""
        used = set(catalog.STAGE_CATEGORY.values()) | set(catalog.STAGE_PREFIX.values())
        self.assertEqual(used - set(catalog.CATEGORIES), set())
        heads = (*catalog.STAGE_PREFIX, *catalog.ENVELOPE_PREFIX)
        launch = [*catalog.STAGE_CATEGORY, *catalog.ADMISSION_WAIT_STAGES]
        outside = [name for names in catalog.OUTSIDE_LAUNCH_STAGES.values() for name in sorted(set(names))]
        self.assertEqual(len(launch), len(set(launch)))
        self.assertEqual(set(launch) & set(outside), set())
        self.assertEqual([name for name in (*launch, *outside) if name.startswith(heads)], [])
        self.assertEqual([(a, b) for a in heads for b in heads if a != b and b.startswith(a)], [])
        self.assertEqual([names for names in catalog.OUTSIDE_LAUNCH_STAGES.values() if len(names) != len(set(names))],
                         [])
        fields = (*catalog.HANDOFF_FIELDS, *catalog.DELIVERY_FIELDS)
        self.assertEqual(len(fields), len(set(fields)), 'a clock field is a hand-off or a delivery field, once')


class StageCatalogCoverageTests(unittest.TestCase):
    """Both directions between the catalog and the span names the producer code writes."""

    def test_the_scan_follows_every_span_call(self) -> None:
        """No span call, import or value use the scan cannot resolve."""
        self.assertEqual(list(scan().problems), [])

    def test_stage_catalog_covers_every_literal_span(self) -> None:
        """Code -> catalog (P3b-12): each written name or f-string prefix belongs to exactly one catalog group."""
        wrong = [f'{item.module}:{item.line} {item.name!r}{"*" if item.prefix else ""} -> {groups(item)}'
                 for item in scan().written if len(groups(item)) != 1]
        self.assertEqual(wrong, [])

    def test_every_catalogued_launch_stage_is_written(self) -> None:
        """Catalog -> code: each launch name and prefix is written outside OUTSIDE_LAUNCH_STAGES' modules.

        ``native_picture_reuse`` is written only through the Short worker's ``picture_stage`` variable, so this also
        proves the scan resolves the variable P3b-12 names.
        """
        launch = [item for item in scan().written if item.module not in catalog.OUTSIDE_LAUNCH_STAGES]
        literal = {item.name for item in launch if not item.prefix}
        expected = (set(catalog.STAGE_CATEGORY) - set(catalog.PLANNED_STAGES)) | set(catalog.ADMISSION_WAIT_STAGES)
        self.assertEqual(sorted(expected - literal), [])
        heads = (*catalog.STAGE_PREFIX, *catalog.ENVELOPE_PREFIX)
        self.assertEqual([head for head in heads if not any(item.name.startswith(head) for item in launch)], [])

    def test_planned_stages_are_catalogued_and_not_written_yet(self) -> None:
        """A planned name has its category, and the commit that writes its span removes it from PLANNED_STAGES."""
        written = {item.name for item in scan().written}
        self.assertEqual(set(catalog.PLANNED_STAGES) - set(catalog.STAGE_CATEGORY), set())
        self.assertEqual(sorted(set(catalog.PLANNED_STAGES) & written), [])

    def test_outside_launch_stages_are_exactly_what_their_modules_write(self) -> None:
        """Catalog -> code for the pre-native paths: each listed module exists and writes exactly its names."""
        for module, names in catalog.OUTSIDE_LAUNCH_STAGES.items():
            with self.subTest(module=module):
                self.assertTrue((PRODUCER / module).is_file())
                found = {(item.name, item.prefix) for item in scan().written if item.module == module}
                self.assertEqual(found, {(name, False) for name in names})


class HandoffFieldTests(unittest.TestCase):
    """The v2 clock fields the catalog names are the ones M-054's frozen_times adds to queue_clock.status."""

    def test_the_catalogued_fields_are_the_ones_frozen_times_adds(self) -> None:
        """Both directions: every key frozen_times adds beyond status's own is catalogued, and nothing else."""
        _, frozen, added = added_fields()
        self.assertEqual(len(constant_keys(frozen)), len(frozen.keys), 'frozen_times keys must be string literals')
        self.assertEqual(added, set(catalog.HANDOFF_FIELDS) | set(catalog.DELIVERY_FIELDS))

    def test_handoff_fields_are_the_ones_read_from_the_handoff_row(self) -> None:
        """HANDOFF_FIELDS are the added keys whose value reads the clock's recorded hand-off row."""
        function, frozen, added = added_fields()
        rows = {target.id for node in ast.walk(function) if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Subscript) and isinstance(node.value.slice, ast.Constant)
                and node.value.slice.value == 'handoff' for target in node.targets if isinstance(target, ast.Name)}
        self.assertEqual(len(rows), 1, 'frozen_times binds the hand-off row to one local name')
        reading = {key.value for key, value in zip(frozen.keys, frozen.values) if key.value in added
                   and any(isinstance(node, ast.Name) and node.id in rows for node in ast.walk(value))}
        self.assertEqual(reading, set(catalog.HANDOFF_FIELDS))

    def test_status_reports_the_frozen_times(self) -> None:
        """queue_clock.status spreads frozen_times into its answer, so the catalogued fields reach the reader."""
        _, status = returned_dict(CLOCK_MODULE, 'status')
        splats = [value for key, value in zip(status.keys, status.values) if key is None]
        calls = [node for value in splats for node in ast.walk(value) if isinstance(node, ast.Call)
                 and getattr(node.func, 'id', None) == 'frozen_times']
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
