"""M-109 (P3b-12): the stage catalog classifies every span name the producer code writes, and names nothing else.

The scan (``_stage_span_scan``) reads every non-test ``.py`` under ``scripts/producer``; its rules and blind spots are
in its docstring, and ``ScannerRefusalTests`` pins the refusals X231 X-R1 added. P3b-12 requires code -> catalog; this
module adds catalog -> code: every catalogued name, prefix, module and clock field is written, except
``PLANNED_STAGES``, which must not be and is pinned to its plan row.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import ast
import unittest

from _stage_span_scan import PRODUCER, SpanCalls, Written, scan
from studio import native_budget_stage_catalog as catalog

CLOCK_MODULE = 'studio/production/queue_clock.py'
HANDOFF_MODULE = 'studio/production/queue_handoff.py'
REFUSED = {  # X231 X-R1: (module, source) the scan must refuse, by the reviewer's mutant id
    'R01 the API rebinds stage': ('stage_timing.py', "def child_span(stage, metadata=None):\n"
                                  "    stage = 'native_x'\n    return stage_span(None, stage, metadata)\n"),
    'R02 a lambda argument shadows a local': ('studio/m.py', "def probe(root):\n    stage = 'native_qc_finish'\n"
                                              "    return lambda stage: stage_span(root, stage)\n"),
    'R02 an except name shadows a local': ('studio/m.py', "def probe(root):\n    stage = 'native_qc_finish'\n    try:\n"
                                           "        pass\n    except OSError as stage:\n        pass\n"
                                           "    return stage_span(root, stage)\n"),
    'R02 an import alias shadows a local': ('studio/m.py', "def probe(root):\n    stage = 'native_qc_finish'\n"
                                            "    from os import sep as stage\n    return stage_span(root, stage)\n"),
    'R03 a raw journal row': ('studio/m.py', "def probe(root):\n    append_row(root, {'stage': 'native_x'})\n"),
    'R04 a span function named in a string': ('studio/m.py', "getattr(stage_timing, 'stage_span')(None, 'native_x')\n"),
    'R05 a renamed import through a re-export': ('studio/m.py', 'from studio.w import stage_span as opener\n'),
}


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
        raise AssertionError(f'{relative}: {function} is not one module-level function returning one dict literal; '
                             'its shape changed, not necessarily its fields: re-read this test against it')
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
        self.assertEqual(catalog.PLANNED_STAGES, {'native_publication_proof': 'N-P1-4'}, 'only plan-allowed names')
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
        reading = {key.value for key, value in zip(frozen.keys, frozen.values) if isinstance(key, ast.Constant)
                   and key.value in added and any(isinstance(node, ast.Name) and node.id in rows
                                                  for node in ast.walk(value))}
        self.assertEqual(reading, set(catalog.HANDOFF_FIELDS))

    def test_status_reports_the_frozen_times(self) -> None:
        """queue_clock.status spreads frozen_times into its answer, so the catalogued fields reach the reader."""
        _, status = returned_dict(CLOCK_MODULE, 'status')
        splats = [value for key, value in zip(status.keys, status.values) if key is None]
        calls = [node for value in splats for node in ast.walk(value) if isinstance(node, ast.Call)
                 and getattr(node.func, 'id', None) == 'frozen_times']
        self.assertEqual(len(calls), 1)


class ScannerRefusalTests(unittest.TestCase):
    """The scan refuses what it cannot follow, rather than resolving it to a wrong or no name (X231 X-R1)."""

    def test_each_hole_the_review_found_is_a_problem(self) -> None:
        """R01, R02, R05, and the cheap closures R03 (raw rows) and R04 (getattr), each as a synthetic module."""
        for case, (module, source) in REFUSED.items():
            with self.subTest(case=case):
                calls = SpanCalls()
                calls.read(module, source)
                self.assertNotEqual(calls.problems, [])
                self.assertEqual(calls.written, [])

    def test_the_same_shapes_without_the_hole_are_followed(self) -> None:
        """Controls: the API forwarding its untouched parameter, one plain local, the markers CLI's raw row."""
        followed = {('stage_timing.py', 'def child_span(stage, metadata=None):\n'
                     '    return stage_span(None, stage, metadata)\n'): [],
                    ('studio/m.py', "def probe(root):\n    stage = 'native_qc_finish'\n"
                     '    return stage_span(root, stage)\n'): [('native_qc_finish', False)],
                    ('stage_timing_markers.py', "append_row(None, {'stage': 'label'})\n"): []}
        for (module, source), expected in followed.items():
            with self.subTest(module=module):
                calls = SpanCalls()
                calls.read(module, source)
                self.assertEqual((calls.problems, [(item.name, item.prefix) for item in calls.written]), ([], expected))


if __name__ == '__main__':
    unittest.main()
