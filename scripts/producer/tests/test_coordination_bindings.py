"""P3a S1 (MASTER-PLAN M-080): the binding plumbing is a pure move; a task holds at most one binding.

The section-binding branches moved from ``tasks``/``task_schema`` into ``task_bindings`` unchanged; the existing
section suites (``test_production_section_results``, ``test_production_sections``, ``test_native_long_section_plan``)
are the move's regression evidence. Until M-082 lands the assignment validator, an ``assignmentBinding`` is refused
wherever it appears (U-T5); tests that pin the one-binding rule for after M-082 patch ``assignment_problem`` to accept.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest
from unittest import mock

from _budget_fixture import task_spec
from studio.production import task_bindings, task_schema
from studio.production.tasks import TaskConflict
from test_production_tasks import TaskCase

ASSIGNMENT = {'schemaVersion': 1, 'kind': 'sniper-assignment', 'outputId': 'A'}   # shape checked from M-082 on
SECTION = {'role': 'author', 'sectionId': 'section-A', 'generation': 1, 'sharedPlanSha256': 'a' * 64,
           'inputIdentity': 'b' * 64, 'frameRange': [0, 75], 'outputRoot': '/TEST/owned', 'authorTaskId': None,
           'inputs': [{'path': '/TEST/shared.json', 'sha256': 'a' * 64, 'bytes': 10}], 'mediaManifest': None}


def accepting() -> mock._patch:
    """M-082's validator accepting every binding (the one-binding rule must hold on its own)."""
    return mock.patch.object(task_bindings, 'assignment_problem', return_value=None)


class Bindings(TaskCase):
    """Rows and declarations through the real task table of a TEST batch."""

    def row(self) -> dict:
        """A stored check task row of batch-auth."""
        self.enqueue(task_spec('probe'))
        return copy.deepcopy(self.task('probe'))

    def section_row(self) -> dict:
        """A full, valid section author row for clip A (the stored row, rebound)."""
        return {**self.row(), 'kind': 'author', 'clipId': 'A', 'sectionBinding': copy.deepcopy(SECTION)}

    def problem(self, row: dict) -> str | None:
        """``production_problem`` of the record with ``row`` stored as task ``probe``."""
        record = self.record()
        record['production']['tasks']['probe'] = row
        return task_schema.production_problem(record)

    def test_section_binding_behavior_unchanged(self) -> None:
        """A valid section row passes; a bad binding, a wrong kind, a run-scoped row and extras alone fail."""
        row = self.section_row()
        self.assertTrue(task_schema._fields_ok(row))
        for change in ({'sectionBinding': {**SECTION, 'generation': 0}}, {'kind': 'review'}, {'clipId': None},
                       {'sectionProgress': {}}):
            with self.subTest(change=sorted(change)):
                self.assertFalse(task_schema._fields_ok({**row, **change}))
        bare = {key: value for key, value in row.items() if key != 'sectionBinding'}
        self.assertTrue(task_schema._fields_ok(bare))

    def test_row_with_both_bindings_refused(self) -> None:
        """A valid section row that also carries an assignment binding names the task, even once assignments validate."""
        row = self.section_row()
        with accepting():
            self.assertEqual(self.problem({**row, 'assignmentBinding': dict(ASSIGNMENT)}), 'task probe fields or identity')
            alone = {key: value for key, value in row.items() if key != 'sectionBinding'}
            self.assertIsNone(self.problem({**alone, 'assignmentBinding': dict(ASSIGNMENT)}))

    def test_definition_includes_assignment_binding(self) -> None:
        """Two declarations differing only in the assignment binding conflict on replay; an identical one replays."""
        self.enqueue(task_spec('probe'))
        with self.assertRaisesRegex(TaskConflict, 'probe already exists with a different definition'):
            self.enqueue(task_spec('probe', assignment_binding=dict(ASSIGNMENT)))
        self.assertEqual(self.enqueue(task_spec('probe'))['replayed'], ['probe'])

    def test_assignment_binding_refused_until_its_validator_lands(self) -> None:
        """U-T5: enqueue and the schema refuse the key by name until M-082; nothing is stored."""
        with self.assertRaisesRegex(ValueError, 'fresh: assignmentBinding is not accepted until its validator lands'):
            self.enqueue(task_spec('fresh', assignment_binding=dict(ASSIGNMENT)))
        self.assertNotIn('fresh', self.record()['production']['tasks'])
        self.assertEqual(self.problem({**self.row(), 'assignmentBinding': dict(ASSIGNMENT)}), 'task probe fields or identity')

    def test_optional_keys_closed(self) -> None:
        """Section extras without a section binding, and an unknown key, are still refused."""
        row = self.row()
        for extra in ('sectionProgress', 'sectionCarryWithdrawal', 'sectionCarry', 'unknownKey'):
            with self.subTest(extra=extra):
                self.assertEqual(self.problem({**row, extra: None}), 'task probe fields or identity')


class Declarations(unittest.TestCase):
    """``check_bindings``/``copy_bindings``/``binding_definition`` on declarations alone."""

    def test_both_declared_is_refused_before_any_validator(self) -> None:
        """A declaration with both bindings is refused by name, without reading the record."""
        spec = task_spec('x', section_binding=dict(SECTION), assignment_binding=dict(ASSIGNMENT))
        with accepting(), self.assertRaisesRegex(ValueError, 'x declares a section and an assignment binding'):
            task_bindings.check_bindings({}, spec)

    def test_copy_and_definition(self) -> None:
        """Only declared bindings are stored; an old row reads as (binding, None)."""
        row: dict = {}
        task_bindings.copy_bindings(row, task_spec('x'))
        self.assertEqual(row, {})
        task_bindings.copy_bindings(row, task_spec('x', assignment_binding=dict(ASSIGNMENT)))
        self.assertEqual(row, {'assignmentBinding': ASSIGNMENT})
        self.assertEqual(task_bindings.binding_definition({'sectionBinding': SECTION}), (SECTION, None))
        with accepting():
            task_bindings.check_bindings({}, task_spec('x', assignment_binding=dict(ASSIGNMENT)))
        self.assertEqual(task_bindings.OPTIONAL_KEYS, frozenset(
            {'sectionBinding', 'sectionProgress', 'sectionCarryWithdrawal', 'sectionCarry', 'assignmentBinding'}))
