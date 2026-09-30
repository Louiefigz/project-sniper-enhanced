"""Optional keys of the production block and their validators (M-044; the seam M-043 completes).

``task_schema.PRODUCTION_KEYS`` stays the required set. A block may also carry the keys in
``PRODUCTION_OPTIONAL``; each is absent until its writer records it and is never defaulted (X50).
``task_schema.production_problem`` makes one call, ``optional_problem``, which runs the validator
of every optional key the block carries.

- ``storage`` is the run's copy of the host storage policy (G10a; written by ``start`` from M-147):
  exactly ``ceilingBytes`` and ``minimumFreeBytes`` (positive integers, bounded like every byte size in
  the authority by ``host_contract.MAX_COUNT``) and ``basis``, which says where the ceiling came from.
- ``closure`` is ``{closedElapsed, unresolvedAtClose}`` (M-043, X37). Until M-043 lands its validator,
  a present ``closure`` is refused by name; M-043 replaces only the body of ``closure_problem``.
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
    """A present ``closure`` is refused until M-043 lands its validator (the key is fixed now, X40)."""
    if 'closure' not in record['production']:
        return None
    return 'production.closure is not accepted until its validator lands (M-043)'


VALIDATORS: dict[str, Callable[[dict], str | None]] = {'closure': closure_problem, 'storage': storage_problem}


def optional_problem(record: dict) -> str | None:
    """The first problem among the optional keys the production block carries, in key order, or None."""
    block = record['production']
    return next(filter(None, (VALIDATORS[key](record) for key in sorted(PRODUCTION_OPTIONAL) if key in block)), None)
