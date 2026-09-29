"""Frozen native-render resource readings and the limits they are judged against.

A snapshot records one bracketed measurement and never decides anything itself;
``native_render_resources`` and ``native_render_policy`` apply the limits. Every
field is evidence retained in owner receipts and resource journals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from native_render_measurements import HostCpuSample
from native_render_processes import ProcessFootprint


@dataclass(frozen=True)
class ResourceSnapshot:
    """Live system pressure and the inclusive footprint of one owned tree."""

    measured_at: float
    physical_bytes: int
    free_percent: float
    swap_used_bytes: int
    compressor_bytes: int
    disk_free_bytes: int
    owned_footprint_bytes: int
    largest_owned_process_bytes: int
    owned_pids: tuple[int, ...]
    processes: tuple[ProcessFootprint, ...]
    identity_verified: bool
    unused_physical_bytes: int
    missing_registered_pids: tuple[int, ...]  # recorded processes that exited
    reused_registered_pids: tuple[int, ...]  # changed while alive, or a changed root: violations
    kernel_pressure_level: int
    memory_sampler: str = 'macos-top-v1'
    host_cpu: HostCpuSample | None = None  # CPU evidence only; no admission or stop input
    recycled_registered_pids: tuple[int, ...] = ()  # exited; PID now held by another process


@dataclass(frozen=True)
class ResourcePolicy:
    """Conservative initial limits; success still requires measured full runs."""

    admission_free_percent: float = 25
    stop_free_percent: float = 10
    maximum_compressor_fraction: float = 0.25
    maximum_owned_gib: float = 16
    maximum_process_gib: float = 8
    maximum_swap_growth_gib: float = 4
    minimum_disk_free_gib: float = 10
    minimum_unused_physical_gib: float = 6
    maximum_snapshot_age_seconds: float = 30

    def __post_init__(self) -> None:
        """Reject invalid or unbounded policies before any execution decision."""
        values = tuple(self.__dict__.values())
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in values):
            raise ValueError("Resource limits must be finite positive numbers")
        if any(not math.isfinite(x) or x <= 0 for x in values):
            raise ValueError("Resource limits must be finite positive numbers")
        if not self.stop_free_percent < self.admission_free_percent < 100:
            raise ValueError("Stop pressure threshold must precede admission headroom")
        if self.maximum_compressor_fraction >= 1:
            raise ValueError("Compressor fraction must be below one")
