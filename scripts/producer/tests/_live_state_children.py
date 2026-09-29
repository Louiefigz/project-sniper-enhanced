"""Parent side of the child live-state tripwire (``_child_live_state/sitecustomize.py``). TEST harness only.

``arm`` makes every Python child this process starts carry the tripwire:

- the tripwire folder first on ``PYTHONPATH`` (the folder holds ``sitecustomize.py`` and nothing else);
- ``SNIPER_TEST_CHILD_REFUSED``: JSON with this process's refused path prefixes and audit-event tables, taken
  from ``_live_state_paths`` (the child imports no engine code and computes nothing itself);
- ``SNIPER_TEST_CHILD_REPORTS``: a directory where a refused child writes one report file before it exits 97;
- ``PYTHONDONTWRITEBYTECODE=1``, so children never write bytecode into the checkout.

An inherited reports directory and inherited prefixes are kept (a child that imports the isolation over decoy
roots refuses both sets). ``new_reports`` returns the report lines this process has not reported yet, so the
isolation fails the test run even when the child's caller swallowed its exit status. Reports are never moved,
so every ancestor sees them. Standard library only; nothing in the product imports this module.

Not covered: a child started with ``-I`` or ``-S``, or with an environment that drops ``PYTHONPATH``, never
loads the tripwire (p0-records/live-root-readers.md).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

CHILD_TRIPWIRE = str(Path(__file__).resolve().parent / '_child_live_state')
CONFIG, REPORTS = 'SNIPER_TEST_CHILD_REFUSED', 'SNIPER_TEST_CHILD_REPORTS'
SCHEMA = 1
_OWN = {'created': None, 'reported': set()}  # the reports directory this process made; report files it reported


def _inherited(environ: dict) -> dict:
    """The prefixes an armed parent passed down, or empty lists when there are none (or they do not parse)."""
    try:
        value = json.loads(environ.get(CONFIG) or '{}')
    except ValueError:
        return {'refused': [], 'writeRefused': []}
    value = value if isinstance(value, dict) else {}
    return {key: [item for item in value.get(key, []) if isinstance(item, str)] for key in ('refused', 'writeRefused')}


def child_config(paths: object, environ: dict) -> dict:
    """The tripwire's JSON value: this process's prefixes (plus inherited ones) and the event tables."""
    inherited = _inherited(environ)
    return {'schema': SCHEMA,
            'refused': sorted(set(paths.REFUSED_PREFIXES) | set(inherited['refused'])),
            'writeRefused': sorted(set(paths.WRITE_REFUSED_PREFIXES) | set(inherited['writeRefused'])),
            'pathEvents': {event: list(positions) for event, positions in paths.PATH_EVENTS.items()},
            'dirFds': {event: {str(path): fd for path, fd in rows.items()} for event, rows in paths.DIR_FDS.items()},
            'readEvents': sorted(paths.READ_EVENTS)}


def _reports_directory(environ: dict) -> str:
    """The inherited reports directory, or a new one this process owns."""
    current = environ.get(REPORTS, '')
    if os.path.isabs(current) and os.path.isdir(current):
        return current
    _OWN['created'] = tempfile.mkdtemp(prefix='sniper-child-refusals-')
    return _OWN['created']


def arm(paths: object, environ: dict = os.environ) -> None:
    """Arm every Python child this process starts from now on (idempotent)."""
    entries = [entry for entry in environ.get('PYTHONPATH', '').split(os.pathsep) if entry and entry != CHILD_TRIPWIRE]
    environ['PYTHONPATH'] = os.pathsep.join([CHILD_TRIPWIRE, *entries])
    environ[CONFIG] = json.dumps(child_config(paths, environ), sort_keys=True)
    environ[REPORTS] = _reports_directory(environ)
    environ['PYTHONDONTWRITEBYTECODE'] = '1'


def reports(directory: str) -> dict[str, str]:
    """Every report file in ``directory`` (name -> its line); an absent directory holds none."""
    if not os.path.isdir(directory):
        return {}
    rows = {}
    for name in sorted(os.listdir(directory)):
        if name.endswith('.report'):
            rows[name] = Path(directory, name).read_text(encoding='utf-8', errors='replace').strip() or name
    return rows


def new_reports(environ: dict = os.environ) -> list[str]:
    """Report lines this process has not reported yet; each is returned once."""
    fresh = {name: line for name, line in reports(environ.get(REPORTS, '')).items() if name not in _OWN['reported']}
    _OWN['reported'].update(fresh)
    return list(fresh.values())


def remove_own_directory() -> None:
    """At exit, remove the reports directory this process made, when no child ever wrote a report there."""
    directory = _OWN['created']
    if directory and os.path.isdir(directory) and not os.listdir(directory):
        os.rmdir(directory)
