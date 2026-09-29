"""Supervisor-side hooks for the shared content-addressed source-frame store.

The Node store (``native_source_store.mjs``) keeps complete frames, per-entry publication locks,
reader leases and collection. Two things must live in the long-lived export supervisor instead:

* the owner lock that reader leases name. Sandboxed media children cannot execute ``/bin/ps``
  (setuid binaries are denied inside Seatbelt), so liveness is a kernel lock held here for the
  whole invocation and released by the kernel when this process exits;
* the render's private SDK view, prepared by one bounded Node step before the SDK CLI render.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_stage_evidence import require

HERE = Path(__file__).resolve().parent
STORE_NAME = 'sniper-source-store-v1'
VIEW_STATUS = 'native-source-view-ready'
OWNER_CLEANUP_RESERVE_SECONDS = 30
_HELD_OWNER_LOCKS: list[int] = []  # Held until this supervisor exits; never closed early.


def _private_directory(path: Path) -> Path:
    """Create or admit one canonical, real, private directory."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.resolve() != path:
        raise RuntimeError(f'Source store directory must be canonical and real: {path}')
    return path


def hold_source_store_owner(cache: Path) -> str:
    """Hold a fresh owner lock for this invocation and return the path leases will name.

    The stub is locked before it is renamed to its final name, so collection can never observe
    an unlocked final owner file that belongs to a live supervisor.
    """
    owners = _private_directory(_private_directory(cache / STORE_NAME) / 'owners')
    name = uuid.uuid4().hex
    stub, final = owners / f'.{name}.creating', owners / f'{name}.lock'
    descriptor = os.open(stub, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.rename(stub, final)
    except BaseException:
        os.close(descriptor)
        raise
    _HELD_OWNER_LOCKS.append(descriptor)
    return str(final)


def source_view_path(request: dict) -> Path:
    """The attempt's deterministic private SDK cache root (same derivation as the Node store)."""
    digest = hashlib.sha256(request['output'].encode()).hexdigest()[:32]
    return Path(request['cache']) / STORE_NAME / 'views' / digest


def owner_remaining_seconds(environment: dict[str, str] | None = None) -> float:
    """Remaining allowance of the supervising owner: the one bound on the view step."""
    from studio.native_export import OWNER_ENV, active_owner_snapshot
    owner = active_owner_snapshot(Path((environment or os.environ)[OWNER_ENV]))
    started = datetime.fromisoformat(owner['startedAt']).timestamp()
    remaining = started + owner['runDeadlineSeconds'] - OWNER_CLEANUP_RESERVE_SECONDS - time.time()
    require(remaining > 0, 'Supervising owner deadline is exhausted before source view preparation')
    return remaining


def prepare_source_view(request: dict, timeout: float | None = None) -> Path:
    """Lease (and publish owned misses of) this attempt's frames, then return the render's view."""
    output = Path(request['output'])
    command = [request['tools']['node'], str(HERE / 'native_source_view.mjs'), str(output / 'export-request.json')]
    subprocess.run(command, check=True, timeout=owner_remaining_seconds() if timeout is None else timeout)
    result = bound_json(output / 'render-source-view/source-view.json')
    view = source_view_path(request)
    require(result.get('status') == VIEW_STATUS and result.get('view') == str(view)
            and view.is_dir() and not view.is_symlink() and view.resolve() == view,
            'Native source view preparation did not publish this attempt view')
    return view
