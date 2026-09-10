"""Original body read request/output lifetimes, separate from original opening IO.

Capture request data before clock callbacks and output identities before control
reads. Raw receipt/entry verification remains in the existing reader. This hold
does not select a result, replay sources, renew time or confer media approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import stat

from guided_body_contract import BodyInvocation
from guided_body_execution import (BodyExecutionClock, BodyHeldFile, _identity,
    _parent_paths, _directory_states)
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_read_clock import (source_color_read_clock_fields,
                                            advance_source_color_read_wall)


@dataclass(frozen=True)
class BodyReadAuthority:
    """Raw hashes held by the actual invocation/completion, never directory lookup."""

    invocation: BodyInvocation
    receipt_sha256: str
    receipt_hash: str


def _request(root: Path, held: BodyReadAuthority) -> tuple:
    """Retain exact request types, identities and values before the first callback."""
    if type(held) is not BodyReadAuthority or type(held.invocation) is not BodyInvocation \
            or set(vars(held)) != {"invocation", "receipt_sha256", "receipt_hash"}:
        raise RuntimeError("body read requires its exact original request type")
    invocation = held.invocation
    return (id(root), str(root), id(held), held.receipt_sha256, held.receipt_hash, id(invocation),
            tuple((key, id(value), str(value)) for key, value in vars(invocation).items()))


class BodyReadLifetime:
    """One local reader's retained originals; never exposed as a caller capability."""

    def __init__(self, root: Path, held: BodyReadAuthority) -> None:
        """Pure construction happens before creating or sampling the read clock."""
        self.root, self.held = root, held
        self.original = hold_read_metadata(_request(root, held))
        self.clock, self.bound, self.wall = None, None, None
        self.files, self.parents, self.directories = (), (), ()

    def _request_current(self) -> None:
        """Mutable frozen-dataclass internals cannot replace the original raw authority."""
        if not same_read_metadata(_request(self.root, self.held), self.original):
            raise RuntimeError("body original read request or raw receipt authority changed")

    def start_clock(self, clock: BodyExecutionClock) -> None:
        """Pure capture immediately after creation, BEFORE the first phase callback."""
        self._request_current()
        if self.clock is not None or type(clock) is not BodyExecutionClock or set(vars(clock)) != {"end", "events"}:
            raise RuntimeError("body read requires its one original newly created body clock")
        self.clock, self.end, self.events = clock, clock.end, clock.events

    def capture(self, clock: BodyExecutionClock) -> None:
        """Capture BOTH output files before control/source callbacks, under original time."""
        self._request_current()
        if clock is not self.clock or self.files:
            raise RuntimeError("body read output lifetime requires its one original body clock")
        self.parents = _parent_paths(tuple(BodyHeldFile(self.root / name, "", ())
            for name in ("body-result.json", "body-worker-entry.json")))
        self.directories = _directory_states(self.parents)
        rows = []
        for name, maximum in (("body-result.json", 16 * 1024 * 1024), ("body-worker-entry.json", 128 * 1024)):
            file = self.root / name
            info = file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
                raise RuntimeError("body read output is not bounded original regular metadata")
            rows.append(BodyHeldFile(file, "", _identity(info)))
        self.files = tuple(rows)
        self.check()

    def bind(self) -> None:
        """Retain the actual already-bound wall clock, not a second budget."""
        self.check()
        if self.bound is not None:
            raise RuntimeError("body read output clock cannot be rebound")
        self.bound = source_color_read_clock_fields(self.clock)
        self.wall = advance_source_color_read_wall(self.clock, None)
        self.check()

    def check(self) -> None:
        """Finite original output/ancestry/request/time sweep without another raw read."""
        self._remaining()
        if _directory_states(self.parents) != self.directories:
            raise RuntimeError("body original read output directory ancestry changed")
        for row in self.files:
            if _identity(row.path.lstat()) != row.identity:
                raise RuntimeError("body original read output file identity changed")
        if _directory_states(self.parents) != self.directories:
            raise RuntimeError("body original read output directory ancestry changed")
        if os.path.lexists(self.root / "body-failed.json"):
            raise RuntimeError("body original read attempt failed; orphan result is unselectable")
        self._request_current()
        self._remaining()

    def _remaining(self) -> None:
        """Save each real body watermark immediately, before any later file callback."""
        self._request_current()
        if self.clock is None or type(self.clock.end) not in (int, float) or not math.isfinite(self.clock.end) \
                or self.clock.end > self.end or self.clock.events is not self.events:
            raise RuntimeError("body original read output clock changed")
        if set(vars(self.clock)) not in ({"end", "events"}, {"end", "events", "wall_deadline_ms", "previous_wall_ms"}):
            raise RuntimeError("body original read clock methods or fields changed")
        if self.bound is not None and source_color_read_clock_fields(self.clock) != self.bound:
            raise RuntimeError("body original bound read output clock changed")
        if self.bound is not None:
            self.wall = advance_source_color_read_wall(self.clock, self.wall)
        BodyExecutionClock.remaining(self.clock)
        if self.bound is not None:
            self.wall = advance_source_color_read_wall(self.clock, self.wall)
        self._request_current()
