"""Optional typed bindings of a task row (P3a S1, MASTER-PLAN M-080): one home for the binding branches.

The section-binding branches moved here unchanged (a pure move, W3-D7), from these source blobs:
- ``bindings_ok`` / ``_section_ok``: ``task_schema._fields_ok`` (task_schema.py ``47f60637f403952e6598b0e7aeb820489bd895ae``);
- ``check_bindings``: ``tasks._check_spec`` (tasks.py ``d9ef12bce27810ec9aaf444ab64a14e9851d4704``);
- ``copy_bindings``: ``tasks.new_row``; ``binding_definition``: ``tasks._definition``'s binding term (same blob).
Every existing record and declaration behaves exactly as before.

A task holds at most one of ``sectionBinding`` and ``assignmentBinding``. The assignment binding has its slot but no
validator yet: until M-082 (P3a S3) lands ``assignments.validate_binding``, the key is refused wherever it appears
(the M-044 ledger row: "the key is refused until its validator lands"). M-082 replaces the body of
``assignment_problem`` and adds its checks to ``check_bindings``.
"""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studio.production.tasks import TaskSpec

SECTION_EXTRAS = frozenset({'sectionProgress', 'sectionCarryWithdrawal', 'sectionCarry'})
OPTIONAL_KEYS = frozenset({'sectionBinding', *SECTION_EXTRAS, 'assignmentBinding'})
NOT_YET = 'assignmentBinding is not accepted until its validator lands (M-082, P3a S3)'


def assignment_problem(binding: object) -> str | None:
    """Why an assignment binding is refused, or None. Until M-082 every binding is refused by name."""
    return NOT_YET


def _section_ok(row: dict) -> bool:
    """The section branch of ``task_schema._fields_ok``, moved verbatim: binding, progress, carry and kind."""
    from studio.production.section_results import validate_binding
    try:
        validate_binding(row['sectionBinding'])
        from studio.production.section_chunk_progress import valid_progress
        valid_progress(row)
        from studio.production.section_chunk_reuse_history import valid_carry_withdrawal
        valid_carry_withdrawal(row)
        from studio.production.section_chunk_carry import valid_carry
        valid_carry(row)
    except (ValueError, TypeError, KeyError):
        return False
    from studio.production.section_assignment_repair import binding_kind
    if not binding_kind(row['sectionBinding'], row['kind'], row['clipId']):
        return False
    return True


def bindings_ok(row: dict) -> bool:
    """A closed row's optional bindings: at most one binding, each valid; section extras only with a section."""
    if 'sectionBinding' in row:
        return 'assignmentBinding' not in row and _section_ok(row)
    if SECTION_EXTRAS & set(row):
        return False
    return 'assignmentBinding' not in row or assignment_problem(row['assignmentBinding']) is None


def check_bindings(record: dict, spec: TaskSpec) -> None:
    """Validate one declaration's bindings before enqueue (the branch moved from ``tasks._check_spec``).

    Raises:
        ValueError: Both bindings are declared, or the assignment binding is refused (named).
    """
    if spec.section_binding is not None and spec.assignment_binding is not None:
        raise ValueError(f'Task {spec.task_id} declares a section and an assignment binding; a task holds at most one')
    if spec.section_binding is not None:
        from studio.production.section_assignment_repair import validate_section_spec
        validate_section_spec(record, spec)
    problem = None if spec.assignment_binding is None else assignment_problem(spec.assignment_binding)
    if problem is not None:
        raise ValueError(f'Task {spec.task_id}: {problem}')


def copy_bindings(row: dict, spec: TaskSpec) -> None:
    """Store a declaration's bindings on its new row (moved from ``tasks.new_row``); absent ones add no key."""
    if spec.section_binding is not None:
        row['sectionBinding'] = deepcopy(spec.section_binding)
    if spec.assignment_binding is not None:
        row['assignmentBinding'] = deepcopy(spec.assignment_binding)


def binding_definition(row: dict) -> tuple:
    """The bindings' part of a task's immutable declaration, for replay comparison.

    A row written before M-080 reads as ``(binding, None)``, and so does its replayed declaration, so they compare
    equal; two declarations differing only in a binding differ here.
    """
    return (row.get('sectionBinding'), row.get('assignmentBinding'))
