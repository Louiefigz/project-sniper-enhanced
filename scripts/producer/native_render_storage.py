"""Predict native-work allocations without consuming the shared disk reserve."""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from cut_preview_io import real_directory
from native_render_resources import GIB, ResourcePolicy


def allocation_requirement(planned_bytes: int, policy: ResourcePolicy) -> dict:
    """Calculate an inclusive byte boundary using the existing resource policy.

    Args:
        planned_bytes: Maximum additional bytes, including owned temporary files.
        policy: The same disk reserve policy used by the native-work owner.

    Returns:
        Exact allocation and reserved headroom in bytes.
    """
    if type(planned_bytes) is not int or planned_bytes < 0:
        raise ValueError('Planned disk allocation must be a nonnegative integer')
    reserve = math.ceil(policy.minimum_disk_free_gib * GIB)
    return {'plannedAllocationBytes': planned_bytes, 'reservedBytes': reserve,
            'requiredFreeBytes': planned_bytes + reserve}


def check_allocation(free_bytes: int, requirement: dict) -> dict:
    """Reject missing capacity before allocation; equality is sufficient.

    Args:
        free_bytes: Actual free capacity on the output filesystem.
        requirement: An allocation_requirement result.

    Returns:
        The admitted calculation, suitable for the calling stage's receipt.
    """
    if type(free_bytes) is not int or free_bytes < 0:
        raise ValueError('Free disk capacity must be a nonnegative integer')
    result = {**requirement, 'observedFreeBytes': free_bytes}
    if free_bytes < requirement['requiredFreeBytes']:
        raise RuntimeError('Native disk allocation refused: '
                           f"{free_bytes} free < {requirement['requiredFreeBytes']} "
                           'planned bytes plus reserved headroom')
    return result


def require_disk_allocation(directory: Path, planned_bytes: int,
                            policy: ResourcePolicy = ResourcePolicy()) -> dict:
    """Measure fresh output-filesystem capacity before a predictable allocation.

    This never removes cached or prior artifacts. Existing files already reduce
    the live free capacity; callers reserve only their additional allocation.
    Continuous owner monitoring remains necessary after this admission check.
    """
    real_directory(directory)
    requirement = allocation_requirement(planned_bytes, policy)
    return {'directory': str(directory),
            **check_allocation(shutil.disk_usage(directory).free, requirement)}
