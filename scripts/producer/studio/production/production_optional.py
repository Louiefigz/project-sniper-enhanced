"""Optional keys of the production block and their validators (M-044; the seam M-043 completes).

``task_schema.PRODUCTION_KEYS`` stays the required set. A block may also carry the keys in
``PRODUCTION_OPTIONAL``; each is absent until its writer records it and is never defaulted (X50).
``task_schema.production_problem`` makes one call, ``optional_problem``, which runs the validator
of every optional key the block carries.

- ``storage`` is the run's copy of the host storage policy (G10a; written by ``start`` from M-147):
  exactly ``ceilingBytes`` and ``minimumFreeBytes`` (positive integers, bounded like every byte size in
  the authority by ``host_contract.MAX_COUNT``) and ``basis``, which says where the ceiling came from.
- ``closure`` is ``{closedElapsed, unresolvedAtClose}`` (M-043, X37), written by ``lifecycle.close_or_drain``
  when a batch closes and accepted only on a closed batch (``closure_problem``).
"""
from __future__ import annotations

from collections.abc import Callable

from studio.production.host_contract import MAX_COUNT

PRODUCTION_OPTIONAL = frozenset({'storage', 'closure'})
STORAGE_KEYS = frozenset({'ceilingBytes', 'minimumFreeBytes', 'basis'})
# computed-default: measured free space minus the reserve, shown to the operator and recorded (X40);
# operator-statement: the per-host value the operator set.
STORAGE_BASES = ('computed-default', 'operator-statement')


def storage_problem(record: dict) -> str | None:
    """The run's storage policy copy, when the block carries one; None when it is valid or absent."""
    block = record['production']
    if 'storage' not in block:
        return None
    storage = block['storage']
    if type(storage) is not dict or set(storage) != STORAGE_KEYS:
        return 'production.storage must hold exactly ceilingBytes, minimumFreeBytes and basis'
    if not all(type(storage[key]) is int and 0 < storage[key] <= MAX_COUNT
               for key in ('ceilingBytes', 'minimumFreeBytes')):
        return 'production.storage ceilingBytes and minimumFreeBytes must be positive whole byte counts'
    if storage['basis'] not in STORAGE_BASES:
        return 'production.storage basis must be computed-default or operator-statement'
    return None


def closure_problem(record: dict) -> str | None:
    """What a closed batch's closure records (M-043, X37): its closing time and each task it left unresolved.

    Only a ``closed`` batch carries it, ``closedElapsed`` equals ``closedAtElapsed``, and each row is a task of
    this batch, listed once with its kind, in the host record's row shape (``host`` a known host or null).
    """
    if 'closure' not in record['production']:
        return None
    from studio.native_budget_schema import BOUNDS
    from studio.production.unresolved_executions import row_problem   # imported here: it imports task_schema
    closure, tasks = record['production']['closure'], record['production']['tasks']
    if record['status'] != 'closed':
        return 'production.closure belongs to a closed batch only'
    if type(closure) is not dict or set(closure) != {'closedElapsed', 'unresolvedAtClose'}:
        return 'production.closure must hold exactly closedElapsed and unresolvedAtClose'
    if type(closure['closedElapsed']) not in (int, float) or closure['closedElapsed'] != record['closedAtElapsed']:
        return 'production.closure closedElapsed must equal the batch closedAtElapsed'
    rows = closure['unresolvedAtClose']
    if type(rows) is not list or len(rows) > BOUNDS['tasks']:
        return f'production.closure unresolvedAtClose must list at most {BOUNDS["tasks"]} rows'
    if problem := next(filter(None, map(row_problem, rows)), None):
        return f'production.closure row: {problem}'
    kinds = {key: row.get('kind') for key, row in tasks.items() if type(row) is dict} if type(tasks) is dict else {}
    listed = {row['taskId'] for row in rows}
    if len(listed) != len(rows) or any(kinds.get(row['taskId']) != row['kind'] for row in rows):
        return 'production.closure lists each task of this batch once, with its kind'
    return None


VALIDATORS: dict[str, Callable[[dict], str | None]] = {'closure': closure_problem, 'storage': storage_problem}


def optional_problem(record: dict) -> str | None:
    """The first problem among the optional keys the production block carries, in key order, or None."""
    block = record['production']
    return next(filter(None, (VALIDATORS[key](record) for key in sorted(PRODUCTION_OPTIONAL) if key in block)), None)
