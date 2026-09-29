"""Identity-bound preview process ownership, snapshots and shutdown for managed Studio views."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

from native_work_lease import NativeWorkLease
from native_render_processes import ProcessIdentity, identity_matches, process_table
from studio.native_runtime import runtime_identity
from studio.studio_server import PS_ENVIRONMENT, ServerRecord, StudioServerError, command_is_preview

# pid, pgid, the exact C-locale lstart ("Wed Sep  9 11:00:00 2026") and the command, which may be empty.
_IDENTITY = r'\s*(\d+)\s+(\d+)\s+([A-Z][a-z]{2} [A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2} \d{4})(?:\s+(.*))?'


def _parse_identity(line: str) -> dict | None:
    """One ``ps -o pid=,pgid=,lstart=,command=`` row as an identity witness, or None."""
    match = re.fullmatch(_IDENTITY, line.rstrip())
    if match is None:
        return None
    return dict(pid=int(match[1]), pgid=int(match[2]), started=match[3], command=match[4] or '')


def _ps(arguments: list[str]) -> tuple[int, str, str]:
    """Run ps in the C locale; arguments of unrelated processes may hold any bytes."""
    output = subprocess.run(['/bin/ps', *arguments], capture_output=True, check=False, timeout=3,
                            env=PS_ENVIRONMENT)
    return (output.returncode, output.stdout.decode('utf-8', errors='replace'),
            output.stderr.decode('utf-8', errors='replace'))


def process_identity(pid: int) -> dict | None:
    """Read a bounded PID/start/group/command witness, never matching by name."""
    code, out, err = _ps(['-p', str(pid), '-o', 'pid=,pgid=,lstart=,command='])
    if code == 1 and not out.strip() and not err.strip():
        return None
    if code != 0:
        raise StudioServerError('Cannot inspect preview process identity')
    identity = _parse_identity(out.strip())
    if identity is None or identity['pid'] != pid:
        raise StudioServerError('Malformed preview process identity')
    return identity


def read_command_table() -> list[dict]:
    """Every process's identity witness; an unreadable row refuses rather than hides a process."""
    code, out, _err = _ps(['-axo', 'pid=,pgid=,lstart=,command='])
    rows = [_parse_identity(line) for line in out.split('\n') if line.strip()]  # ps escapes \n in arguments only
    if code != 0 or not rows or None in rows:
        raise StudioServerError('Cannot read the process table to find an unfinished launch')
    return rows


def served_cli(command: str) -> str | None:
    """The CLI a ``node <cli> preview ...`` command runs, or None for any other command."""
    cli, found, _rest = command.partition(' ')[2].partition(' preview ')
    return cli if found else None


def _served_port(command: str, project: str) -> int | None:
    """The port of a Sniper-runtime preview serving exactly this project, else None."""
    port = command.partition(f' preview {project} --port ')[2].partition(' ')[0]
    cli = served_cli(command)
    if not (port.isascii() and port.isdigit()) or not (cli or '').startswith('/') or runtime_identity(cli) is None:
        return None
    return int(port) if command_is_preview(command, project, int(port)) else None


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


def record_from(value: dict) -> ServerRecord:
    """Convert the validated central entry to the existing Studio record type."""
    item = value['record']
    return ServerRecord(item['port'], item['pid'], item['url'], item['startedAt'])


def matches(value: dict) -> bool:
    """A PID reused even for the same command is not our registered server."""
    return process_identity(value['identity']['pid']) == value['identity']


def read_tree_table() -> dict:
    """Read ancestry without collecting unrelated process command lines."""
    code, out, _err = _ps(['-axo', 'pid=,ppid=,pgid=,lstart='])
    if code != 0:
        raise StudioServerError('Cannot read the process table')
    return process_table(out)


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
    except (ProcessLookupError, PermissionError):  # gone, or not ours to signal: never verified here
        return False


def stop_registered(persist: Callable[[dict], None], value: dict) -> dict:
    """Stop exactly one registered view; keep its record on failed cleanup, never signal user apps."""
    if value['state'] == 'stopped':
        return value
    _validate_running(value)
    owned = snapshot_owned(value)
    persist(owned)
    cleanup = terminate_tree(owned)
    if not cleanup['verified']:
        raise StudioServerError('Registered preview did not exit; replacement refused')
    stopped = dict(owned, state='stopped', stoppedAt=time.time(), cleanup=cleanup)
    persist(stopped)
    return stopped


def launch_servers(project: str, port: int | None, cli: str | None) -> list[dict]:
    """The server an interrupted launch started: this project, the recorded port and CLI.

    An interrupted opener may never learn its server's PID, so the server is found by its exact
    command. A record without its port and CLI (written by earlier code) is never matched by
    command; only its retained identities count. Stock servers and other checkouts never match.
    """
    if port is None or cli is None:
        return []
    return [row for row in read_command_table()
            if _served_port(row['command'], project) == port and served_cli(row['command']) == cli]


def launch_survivors(value: dict) -> list[dict]:
    """Every live process an unfinished launch left: retained witnesses and each server's tree."""
    servers = launch_servers(value['project'], value.get('port'), value.get('cli'))
    trees = [snapshot_owned({'identity': server}) for server in servers]
    rows = [row for tree in trees for row in live_owned(tree)]
    rows += live_owned(value) if value.get('processes') else []
    return list({json.dumps(row, sort_keys=True): row for row in rows}.values())


def observe_survivors(value: dict) -> dict:
    """An unfinished launch's live processes, signalling nothing."""
    survivors = launch_survivors(value)
    reason = 'unfinished launch still running' if survivors else 'no process of the unfinished launch runs'
    return dict(verified=not survivors, survivors=survivors, signals=[], reason=reason)


def discharge_survivors(value: dict) -> dict:
    """Stop an unfinished launch's processes by exact identity; verified only once none remains."""
    survivors = launch_survivors(value)
    if not survivors:
        return dict(verified=True, survivors=[], signals=[], reason='no process of the unfinished launch runs')
    cleanup = terminate_tree({'processes': survivors})
    remaining = launch_survivors(value)
    return dict(cleanup, verified=cleanup['verified'] and not remaining, survivors=remaining,
                reason='unfinished launch stopped by identity')


def settle_launch(persist: Callable[[dict], None], entry: dict, discharge: bool = False) -> dict:
    """Close an unfinished launch's fence once none of its processes runs; ``discharge`` stops them.

    Inside a registry transaction no opener is still working on a 'launching' record (the lock
    dies with its holder): the launch was interrupted or kept survivors, found by retained
    identity or by exact command. Its fence lasts only while one of them runs.
    """
    if entry['state'] != 'launching':
        return entry
    cleanup = (discharge_survivors if discharge else observe_survivors)(entry)
    settled = dict(entry, cleanup=cleanup, processes=cleanup['survivors'])
    if cleanup['verified']:
        settled.update(state='stopped', stoppedAt=time.time())
    persist(settled)
    if discharge and not cleanup['verified']:
        pids = [row['pid'] for row in cleanup['survivors']]
        raise StudioServerError(f"Unfinished preview launch for {entry['project']} did not exit (pids {pids})")
    return settled


def discharge_launch(project: str, port: int, pid: int | None) -> dict:
    """Stop exactly the preview one failed startup launched and verify its tree is gone.

    Only this project's preview command on this port is signalled here. The PID is this launch's
    own child, so a live process with another command stays unverified (retained for ``stop``);
    without the launched PID the outcome is unknown and stays unverified.
    """
    if pid is None:
        return dict(verified=False, survivors=[], reason='launched process identity unknown')
    identity = process_identity(pid)
    if identity is None:
        return dict(verified=True, survivors=[], reason='launched preview already exited')
    if not command_is_preview(identity['command'], project, port):  # this launch's own PID: never "exited"
        witness = {key: identity[key] for key in ('pid', 'pgid', 'started')}
        return dict(verified=False, survivors=[witness], reason='launched process runs an unexpected command')
    return dict(terminate_tree(snapshot_owned({'identity': identity})), reason='failed startup stopped by identity')
