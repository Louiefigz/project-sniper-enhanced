"""TEST driver: the unmodified base-engine (4a15560) pool client as a separate process.

Runs native_pool_driver.py's commands (hold, queue, ...) with the pool modules imported
from base_pool_4a15560/, byte-identical copies of the base engine's pool client (checked
against SOURCE.json before import). Only helpers the base pool imports from the shared tree
(headless.durable_files, native_render_processes) come from this checkout. It never
touches the canonical host namespace: native_pool_driver.isolate() redirects it first.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BASE = HERE.parent / 'base_pool_4a15560'
sys.path[:0] = [str(BASE), str(HERE.parents[2]), str(HERE.parents[1]), str(HERE.parent)]


def verify_base() -> None:
    """Refuse to run unless every vendored module still matches its recorded base bytes."""
    source = json.loads((BASE / 'SOURCE.json').read_text())
    for name, row in source['files'].items():
        if hashlib.sha256((BASE / name).read_bytes()).hexdigest() != row['sha256']:
            raise SystemExit(f'TEST base pool fixture {name} differs from {source["commit"]}')


verify_base()
import native_work_lease  # noqa: E402  (base copy: imported first so every later import reuses it)
import native_work_pool  # noqa: E402

if {Path(module.__file__).resolve().parent for module in (native_work_pool, native_work_lease)} != {BASE}:
    raise SystemExit('TEST base pool fixture was not the imported pool client')

import native_pool_driver  # noqa: E402


def disk_view(project: str, *roots: str) -> None:
    """Report the disk figures the base client computes for each root, in one ledger transaction.

    The base client charges a member only on its recorded root device (diskDevice and
    diskReservationBytes); this is exactly what its admission would see for these roots.
    """
    import time
    import native_work_pool_state as state
    from native_work_pool_observe import observe
    physical = native_work_pool.policy.host_identity()['memsizeBytes']
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        rows = native_work_pool._member_charges(observe(namespace), physical)
        for root in roots:
            decision = native_work_pool.Decision(None, 0, 0, 0)
            native_work_pool._disk_reasons(decision, rows, native_work_pool.PoolRequest('heavy', project, root=root))
            native_pool_driver.emit(event='disk-view', root=root, device=decision.device,
                                    reservedByOthersBytes=decision.context['diskReservedByOthersBytes'])


def _attempt(request: object, held: list) -> None:
    """One admission attempt of the step client; its ticket stays held on refusal."""
    try:
        held.append(native_work_lease.NativeWorkLease.acquire(request.lane, request.project, request=request))
    except native_work_lease.NativeWorkBusy as error:
        native_pool_driver.emit(event='refused', error=type(error).__name__, reason=str(error))
        return
    native_pool_driver.emit(event='admitted', nonce=held[0].nonce)


def step(lane: str, project: str) -> None:
    """One base request driven line by line: 'try' attempts once, 'done' completes; one event per line.

    Lets a test interleave the base client with this engine's requests deterministically.
    """
    request, held = native_work_pool.PoolRequest(lane, project, declares_launch=True), []
    native_pool_driver.emit(event='ready')
    actions = {'try': lambda: held or _attempt(request, held), 'done': lambda: held and _complete(held.pop())}
    for line in sys.stdin:
        actions.get(line.strip(), lambda: None)()
    request.withdraw()


def _complete(lease: object) -> None:
    """Complete one step-client member and report it."""
    lease.complete()
    lease.close()
    native_pool_driver.emit(event='completed')


if __name__ == '__main__':
    native_pool_driver.main({'disk-view': disk_view, 'step': step})
