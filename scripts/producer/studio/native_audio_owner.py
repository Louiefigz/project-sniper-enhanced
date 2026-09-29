"""The audio-stage worker's side of its closed live-owner contract.

``native_export.launch_binding`` validates the one audio worker command before pool
admission and ``worker_environment`` hands the child ``SNIPER_NATIVE_AUDIO_REQUEST``,
its owner receipt and the supervisor PID. This module is what the worker checks with
them. The export check cannot be reused unchanged, because it expects ``export-request.json``.
A refusal raises ``NativeOwnerRefused`` and writes nothing into the stage. The CLI prints
one JSON refusal line (exit 2). The supervisor's failure record reads that line back
(``worker_refusal``) so the stage failure names the real cause and category.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_audio_seal import OWNER_NAME, REQUEST_NAME, RESULT_NAME
from studio.native_export import (AUDIO_REQUEST_ENV, AUDIO_SCOPE, AUDIO_WORKER, OWNER_ENV, PID_ENV,
                                  SANDBOX_PREFIX, active_owner_snapshot)
from studio.native_runtime import digest

# The child is launched after admission; its receipt then reads 'preparing' until the
# supervisor persists 'running'. Admission itself is proved by pool/queue, not status.
LIVE_OWNER_STATES = ('preparing', 'running')
REFUSED = 'audio-owner-refused'
DEADLINE = 'budget-exhausted'  # the budget's own category for a spent inherited deadline
REFUSAL_CATEGORIES = (REFUSED, DEADLINE)
REFUSAL_PHASE = 'audio-stage-worker'
LOG_TAIL_BYTES = 64 * 1024


class NativeOwnerRefused(ValueError):
    """The audio worker has no live admitted owner bound to its exact request."""

    def __init__(self, message: str, category: str = REFUSED) -> None:
        """Keep the refusal category for the owner's failure record and the budget."""
        self.category = category
        super().__init__(message)


def refuse_unless(value: bool, message: str, category: str = REFUSED) -> None:
    """Raise the audio worker's specific refusal; nothing is written into the stage."""
    if not value:
        raise NativeOwnerRefused(f'Native audio worker refused: {message}', category)


def require_live_supervisor() -> None:
    """The supervisor that launched this worker is still its parent; an orphan never publishes."""
    supervisor = os.environ.get(PID_ENV, '')
    refuse_unless(supervisor.isdigit() and int(supervisor) > 1 and int(supervisor) == os.getppid(),
                  'its supervisor is not alive as its parent')


def require_owned_audio_worker(request_file: Path) -> dict:
    """Return the exact audio request only when its live, admitted owner launched this worker.

    The stage's own owner receipt must have pinned these request bytes and this worker
    command. It must still be active and admitted in the request's pool class, hold a
    live inherited deadline and be this process's actual parent.
    """
    refuse_unless(os.environ.get(AUDIO_REQUEST_ENV) == str(request_file),
                  'no live audio-stage owner started it; run native_audio_stage.py prepare')
    try:
        owner, request = audio_owner_evidence(request_file)
        require_audio_binding(owner, request, request_file)
        require_audio_liveness(owner, request)
    except NativeOwnerRefused:
        raise
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise NativeOwnerRefused(f'Native audio worker refused: unreadable owner evidence ({error})') from error
    return request


def audio_owner_evidence(request_file: Path) -> tuple[dict, dict]:
    """Read the stage's own owner receipt, then the request bytes that owner pinned."""
    owner_file = Path(os.environ.get(OWNER_ENV, ''))
    refuse_unless(request_file.name == REQUEST_NAME and owner_file == request_file.with_name(OWNER_NAME),
                  "the named owner receipt is not this audio stage's own")
    refuse_unless(owner_file.is_file(), 'its owner receipt is missing')
    owner = active_owner_snapshot(owner_file)
    pinned = owner.get('additionalFilePinsBefore', {}).get(str(request_file))
    refuse_unless(isinstance(pinned, str) and pinned == digest(request_file),
                  'its owner does not bind this exact audio request')
    return owner, bound_json(request_file, pinned)


def require_audio_binding(owner: dict, request: dict, request_file: Path) -> None:
    """The owner launched exactly this worker for this request, project and output."""
    root, args = request_file.parent, owner.get('args')
    refuse_unless(request.get('scope') == AUDIO_SCOPE and request.get('stageRoot') == str(root)
                  and owner.get('project') == request.get('project')
                  and owner.get('output') == str(root / RESULT_NAME)
                  and isinstance(args, list) and tuple(args[:2]) == SANDBOX_PREFIX  # args[4:] fixes len 7
                  and args[4:] == [str(AUDIO_WORKER), 'worker', str(request_file)]
                  and Path(args[3]).resolve() == Path(sys.executable).resolve(),
                  'its owner does not bind this exact audio request')


def require_audio_liveness(owner: dict, request: dict) -> None:
    """The owner is active, admitted, within its inherited deadline and this worker's parent."""
    refuse_unless(owner.get('status') in LIVE_OWNER_STATES and not owner.get('completedAt')
                  and not owner.get('abortReason') and owner.get('pid', os.getpid()) == os.getpid(),
                  'its owner is not the active owner of this worker')
    pool, queue = owner.get('pool'), owner.get('queue')
    refuse_unless(isinstance(pool, dict) and pool.get('class') == request['leaseClass']
                  and isinstance(queue, dict) and queue.get('admitted') is True,
                  "its owner was not admitted to the request's pool class")
    refuse_unless('productionAllocation' in owner, 'its owner recorded no inherited deadline')
    if owner['productionAllocation'] is not None:
        from studio.native_budget_clock import allocation_remaining
        refuse_unless(allocation_remaining(owner['productionAllocation']) > 0,
                      "its owner's inherited production deadline has passed", DEADLINE)
    require_live_supervisor()
    refuse_unless(owner.get('supervisorPid') == os.getppid(), 'its owner receipt names another supervisor')


def refusal_line(error: NativeOwnerRefused) -> str:
    """The one JSON line a refused worker prints for its supervisor's log."""
    return json.dumps({'status': 'refused', 'phase': REFUSAL_PHASE, 'category': error.category,
                       'error': str(error)})


def worker_refusal(root: Path, owner: dict) -> dict | None:
    """Return the refused worker's own JSON line from this stage's owner log, if it exited 2."""
    name = owner.get('logPath')
    if owner.get('exitCode') != 2 or not isinstance(name, str):
        return None
    log = Path(name)
    if log.parent != root or log.is_symlink() or not log.is_file():
        return None
    with log.open('rb') as handle:
        handle.seek(max(0, log.stat().st_size - LOG_TAIL_BYTES))
        lines = handle.read().decode('utf-8', 'replace').splitlines()
    for line in reversed(lines):
        row = parsed_refusal(line)
        if row is not None:
            return row
    return None


def parsed_refusal(line: str) -> dict | None:
    """One recognized refusal row: exact phase, known category and a string reason."""
    try:
        row = json.loads(line)
    except ValueError:
        return None
    recognized = (isinstance(row, dict) and row.get('status') == 'refused' and row.get('phase') == REFUSAL_PHASE
                  and row.get('category') in REFUSAL_CATEGORIES and isinstance(row.get('error'), str))
    return row if recognized else None
