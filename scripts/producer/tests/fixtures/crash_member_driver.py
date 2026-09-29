"""TEST driver: a fenced member of this engine that a test SIGKILLs (never completes on its own).

Argv: <command> <state root> <record dir> <project> <paths...>. Commands:
  sibling <member root>      admitted with its root on another APFS volume (fenced at admission)
  offroot <attempt> <cache>  admitted on a TEST non-APFS attempt volume (unfenced), then grows
                             onto a TEST cache volume, which fences it at expansion
Each prints one JSON line per step and then blocks until killed. Never touches the host pool.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[2]), str(HERE.parents[1]), str(HERE.parent)]

from native_pool_driver import emit, isolate  # noqa: E402
import native_work_lease as work  # noqa: E402
import native_work_pool as pool  # noqa: E402

GIB = 2 ** 30


def _admit(project: str, root: str) -> object:
    """Admit one declared heavy member and report its fence and recorded charges."""
    lease = work.NativeWorkLease.acquire('heavy', project, request=pool.PoolRequest(
        'heavy', project, root=root, declares_launch=True))
    emit(event='admitted', nonce=lease.nonce, fence=len(lease.fence), **_charges(lease))
    return lease


def _charges(lease: object) -> dict:
    """The memory charges older clients and this client read from the record."""
    return {'reservationBytes': lease.record['reservationBytes'],
            'guardReservationBytes': lease.record['guardReservationBytes']}


def offroot(project: str, attempt: str, cache: str) -> object:
    """Unfenced on a TEST non-APFS attempt volume, then fenced by growing onto a TEST cache volume."""
    import native_work_pool_disk as disk
    from native_work_pool_expand import expand_disk
    real = disk.filesystem
    volumes = {attempt: disk.Filesystem(8, 'filesystem:8', 500 * GIB),
               cache: disk.Filesystem(7, 'filesystem:7', 500 * GIB)}
    disk.filesystem = lambda path: volumes.get(path) or real(path)
    lease = _admit(project, attempt)
    expand_disk(lease, {cache: GIB})
    emit(event='expanded', fence=len(lease.fence), **_charges(lease))
    return lease


def main() -> None:
    """Dispatch, then hold the member until this process is killed."""
    command, root, record, project, *paths = sys.argv[1:]
    isolate(root, record)
    lease = _admit(project, paths[0]) if command == 'sibling' else offroot(project, *paths[:2])
    sys.stdin.read()
    lease.close()


if __name__ == '__main__':
    main()
