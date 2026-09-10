"""Private preview registry and identity-bound shutdown for the native lane."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from headless.durable_files import read_private_file, write_pending_replace
from native_work_lease import NativeWorkLease
from native_render_processes import ProcessIdentity, identity_matches, process_table
from studio.studio_server import ServerRecord, StudioServerError, command_is_preview


def process_identity(pid: int) -> dict | None:
    """Read a bounded PID/start/group/command witness, never matching by name."""
    output = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'pid=,pgid=,lstart=,command='],
                            check=False, text=True, capture_output=True, timeout=3)
    if output.returncode == 1 and not output.stdout.strip() and not output.stderr.strip():
        return None
    if output.returncode != 0:
        raise StudioServerError('Cannot inspect preview process identity')
    pattern = r'\s*(\d+)\s+(\d+)\s+(.{24})\s+(.+)'
    match = re.fullmatch(pattern, output.stdout.strip())
    if match is None or int(match[1]) != pid:
        raise StudioServerError('Malformed preview process identity')
    return dict(pid=pid, pgid=int(match[2]), started=match[3], command=match[4])


def verified_preview(project: str, record: ServerRecord) -> dict:
    """Bind the exact preview command, accepting dot only with verified cwd."""
    identity = process_identity(record.pid)
    if identity is None:
        raise StudioServerError('Preview exited before registry publication')
    command = identity['command']
    if ' preview . --port ' in command:
        result = subprocess.run(['/usr/sbin/lsof', '-a', '-p', str(record.pid), '-d', 'cwd', '-Fn'],
                                capture_output=True, text=True, check=True, timeout=3)
        if result.stdout.splitlines().count('n' + project) != 1:
            raise StudioServerError('Relative preview project has an unverified working directory')
        command = command.replace(' preview . --port ', f' preview {project} --port ', 1)
    if not command_is_preview(command, project, record.port):
        raise StudioServerError('Process is not the exact requested HyperFrames preview')
    return identity


def read_preview(lease: NativeWorkLease) -> dict | None:
    """Read bounded private state; malformed or unfinished state fences startup."""
    try:
        os.stat('preview.json', dir_fd=lease.dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    value = json.loads(read_private_file(lease.dir_fd, 'preview.json'))
    if not isinstance(value, dict) or value.get('schemaVersion') != 1:
        raise StudioServerError('Invalid native preview registry')
    if value.get('state') not in {'running', 'stopped'}:
        raise StudioServerError('Previous preview launch/cleanup is unverified')
    if value['state'] == 'running':
        _validate_running(value)
    return value


def _validate_running(value: dict) -> None:
    """Reject malformed registry data before considering any process signal."""
    project, record, identity = (value.get(key) for key in ('project', 'record', 'identity'))
    if not isinstance(project, str) or str(Path(project).resolve()) != project:
        raise StudioServerError('Preview registry project must be canonical')
    if not isinstance(record, dict) or set(record) != {'port', 'pid', 'url', 'startedAt'}:
        raise StudioServerError('Preview registry record is malformed')
    if not isinstance(identity, dict) or set(identity) != {'pid', 'pgid', 'started', 'command'}:
        raise StudioServerError('Preview registry identity is malformed')
    NativeWorkLease._validate_identity({key: identity[key] for key in ('pid', 'pgid', 'started')})
    if record['pid'] != identity['pid'] or type(record['port']) is not int or not 1 <= record['port'] <= 65535:
        raise StudioServerError('Preview registry identifiers disagree')
    if not isinstance(identity['command'], str) or not identity['command']:
        raise StudioServerError('Preview registry command is missing')


def write_preview(lease: NativeWorkLease, value: dict) -> None:
    """Publish runtime state outside editable composition directories."""
    write_pending_replace(lease.dir_fd, ('preview.pending.json', 'preview.json'),
                          (json.dumps(value, sort_keys=True) + '\n').encode())


def record_from(value: dict) -> ServerRecord:
    """Convert the validated central entry to the existing Studio record type."""
    item = value['record']
    return ServerRecord(item['port'], item['pid'], item['url'], item['startedAt'])


def matches(value: dict) -> bool:
    """A PID reused even for the same command is not our registered server."""
    return process_identity(value['identity']['pid']) == value['identity']


def read_tree_table() -> dict:
    """Read ancestry without collecting unrelated process command lines."""
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='],
                            capture_output=True, text=True, check=True, timeout=3)
    return process_table(result.stdout)


def snapshot_owned(value: dict) -> dict:
    """Remember browser descendants before their preview parent can disappear."""
    table = read_tree_table()
    root = {key: value['identity'][key] for key in ('pid', 'pgid', 'started')}
    known = value.get('processes', [root])
    for row in known:
        NativeWorkLease._validate_identity(row)
    live = {row['pid'] for row in known if identity_matches(table, ProcessIdentity(**row))}
    if not matches(value):
        live.discard(root['pid'])
    while True:
        added = {pid for pid, row in table.items() if row[0] in live} - live
        if not added:
            break
        live.update(added)
    retained = {json.dumps(row, sort_keys=True): row for row in known}
    for pid in live:
        row = dict(pid=pid, pgid=table[pid][1], started=table[pid][2])
        retained[json.dumps(row, sort_keys=True)] = row
    return dict(value, processes=list(retained.values()))


def live_owned(value: dict) -> list[dict]:
    """Find retained matching children even after reparenting or root exit."""
    table = read_tree_table()
    return [row for row in value['processes'] if identity_matches(table, ProcessIdentity(**row))]


def terminate_tree(value: dict) -> dict:
    """Stop only identities established through the exact preview's ancestry."""
    signals = []
    for selected, seconds in ((signal.SIGTERM, 5), (signal.SIGKILL, 2)):
        signals.extend(_signal_tree(value, selected))
        deadline = time.monotonic() + seconds
        while live_owned(value) and time.monotonic() < deadline:
            time.sleep(0.1)
        if not live_owned(value):
            return dict(verified=True, survivors=[], signals=signals)
    return dict(verified=False, survivors=live_owned(value), signals=signals)


def _signal_tree(value: dict, selected: signal.Signals) -> list[dict]:
    """Signal the recorded tree without broad process-name or group kills."""
    events = []
    for row in live_owned(value):
        if _signal_process(row, selected):
            events.append(dict(pid=row['pid'], signal=selected.name))
    return events


def _signal_process(row: dict, selected: signal.Signals) -> bool:
    """Recheck each retained identity immediately before an exact-PID signal."""
    if not identity_matches(read_tree_table(), ProcessIdentity(**row)):
        return False
    try:
        os.kill(row['pid'], selected)
        return True
    except ProcessLookupError:
        return False


def stop_registered(lease: NativeWorkLease, value: dict) -> None:
    """Keep the record on failed cleanup; never signal user apps or delete media."""
    if value['state'] == 'stopped':
        return
    _validate_running(value)
    owned = snapshot_owned(value)
    write_preview(lease, owned)
    cleanup = terminate_tree(owned)
    if not cleanup['verified']:
        raise StudioServerError('Registered preview did not exit; replacement refused')
    write_preview(lease, dict(owned, state='stopped', stoppedAt=time.time(), cleanup=cleanup))
