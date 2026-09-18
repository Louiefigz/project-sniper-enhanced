"""Palmier compatibility adapter for the shared producer subprocess budget."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from headless.process_runner import ProcessDeadlinePolicyError
from headless.process_runner import process_timeout as _process_timeout
from headless.process_runner import use_process_deadline as _use_process_deadline
from palmier.mcp_client import PalmierError


@contextmanager
def use_process_deadline(deadline: Any) -> Iterator[None]:
    """Keep the connected caller's exception contract and shared nested clock."""
    try:
        with _use_process_deadline(deadline):
            yield
    except ProcessDeadlinePolicyError as error:
        raise PalmierError(str(error)) from error


def process_timeout(default_s: float = 300.0) -> float:
    """Retain the Palmier exception type for invalid timeout policy."""
    try:
        return _process_timeout(default_s)
    except ProcessDeadlinePolicyError as error:
        raise PalmierError(str(error)) from error
