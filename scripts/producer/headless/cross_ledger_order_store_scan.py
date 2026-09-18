"""Two-pass exact-set scan for cross-ledger order records."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .durable_files import exact_directory_entries
from .wire_identity import same_wire_value

_T = TypeVar("_T")


class CrossLedgerOrderScanError(RuntimeError):
    """The retained order set changed during observation."""


def load_stable_cross_ledger_order_set_v1(
    store_fd: int,
    names: tuple[str, ...],
    loader: Callable[[int, str], _T],
) -> tuple[_T, ...]:
    """Read every row twice around exact name-set checks."""
    first = tuple(loader(store_fd, name) for name in names)
    if not exact_directory_entries(store_fd, frozenset(names)):
        raise CrossLedgerOrderScanError("cross-ledger order set changed")
    second = tuple(loader(store_fd, name) for name in names)
    stable = len(first) == len(second) and all(
        same_wire_value(left, right) for left, right in zip(first, second)
    )
    if not stable or not exact_directory_entries(store_fd, frozenset(names)):
        raise CrossLedgerOrderScanError("cross-ledger order set changed")
    return first
