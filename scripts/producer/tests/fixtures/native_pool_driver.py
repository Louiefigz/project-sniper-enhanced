"""TEST driver: separate supervisor processes for real multi-process pool tests.

Every command first points the pool at a private TEST namespace (argv root) and,
when a TEST record folder is given, at the TEST fixture host and TEST engine identity. It never touches the
canonical host namespace. Output is one JSON line per event on stdout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[2]), str(HERE.parents[1])]

import native_work_lease as work  # noqa: E402
import native_work_pool as pool  # noqa: E402


def isolate(root: str, record: str) -> None:
    """Redirect the namespace (and optionally the record/host) to TEST values."""
    work.state_root = lambda: Path(root)
    if record != '-':
        import native_work_pool_policy as policy
        import native_work_qualification as qualification
        import native_work_workload as workloads
        from _native_pool_fixture import TEST_ENGINE, TEST_HOST
        policy.host_identity = lambda: dict(TEST_HOST)
        qualification.record_directory = lambda: Path(record)
        workloads.current_engine = lambda: TEST_ENGINE['identity']


def emit(**values: object) -> None:
    """Report one event for the parent test."""
    print(json.dumps(values), flush=True)


def fixed_free(free: str) -> None:
    """TEST volumes: real devices and spaces, but every filesystem reports the given free bytes."""
    import native_work_pool_disk as disk
    real = disk.filesystem
    disk.filesystem = lambda path: real(path)._replace(free=int(free))


def crash_during_publish(name: str, point: str) -> None:
    """TEST fault: exit abruptly while publishing one record (no cleanup, as after SIGKILL)."""
    import native_work_pool_state as state
    original = state.write_pending_replace
    def publish(directory: int, names: tuple[str, str], data: bytes) -> None:
        """Die before writing, after the pending bytes, or after the atomic replace."""
        if names[1] == name and point == 'before-publish':
            os._exit(3)
        if names[1] == name and point == 'pending-written':
            descriptor = os.open(names[0], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600, dir_fd=directory)
            os.write(descriptor, data)
            os._exit(3)
        original(directory, names, data)
        if names[1] == name and point == 'after-publish':
            os._exit(3)
    state.write_pending_replace = publish


def expand(project: str, attempt: str, size: str, free: str, point: str) -> None:
    """Admit a declared member, wait for 'go', grow its disk reservation, then hold until stdin closes."""
    fixed_free(free)
    lease = work.NativeWorkLease.acquire('heavy', project, request=pool.PoolRequest(
        'heavy', project, root=attempt, declares_launch=True))
    emit(event='admitted', nonce=lease.nonce, pid=os.getpid())
    sys.stdin.readline()
    if point != 'none':
        crash_during_publish(lease.marker, point)
    emit(event='transacting')
    try:
        from native_work_pool_expand import expand_disk
        grant = expand_disk(lease, {attempt: int(size)})
    except work.NativeWorkBusy as error:
        emit(event='refused', reason=str(error))
    else:
        emit(event='expanded', grant=grant)
    sys.stdin.readline()
    lease.complete()
    lease.close()


def admit_disk(project: str, root: str, size: str, free: str) -> None:
    """Wait for 'go', attempt one admission reserving the given disk bytes, then hold until stdin closes."""
    fixed_free(free)
    sys.stdin.readline()
    emit(event='transacting')
    request = pool.PoolRequest('heavy', project, root=root, disk_bytes=int(size), declares_launch=True)
    try:
        lease = work.NativeWorkLease.acquire('heavy', project, request=request)
    except work.NativeWorkBusy as error:
        emit(event='refused', reason=str(error))
        return
    finally:
        request.withdraw()
    emit(event='admitted', nonce=lease.nonce)
    sys.stdin.readline()
    lease.complete()
    lease.close()


def hold(lane: str, project: str, seconds: float, flags: list[str]) -> None:
    """Admit a declared member, optionally launch/record a child (--child), hold, then complete.

    --fenced asks for a compatibility fence (TEST stand-in for an off-root disk reservation).
    """
    child = '--child' in flags
    extra = {'fence_reasons': ('TEST off-root disk reservation',)} if '--fenced' in flags else {}
    request = pool.PoolRequest(lane, project, declares_launch=True, **extra)
    started = time.monotonic()
    try:
        lease = pool.acquire_until(lane, project, started + 30, request)
    except work.NativeWorkBusy as error:
        emit(event='refused', error=type(error).__name__, reason=str(error), at=time.time())
        return
    info = {'event': 'admitted', 'nonce': lease.nonce, 'queued': time.monotonic() - started, 'at': time.time(),
            'mode': lease.admission['mode'], 'pid': os.getpid(), 'chargedBytes': lease.admission.get('chargedBytes'),
            'diskReservedByOthersBytes': lease.admission.get('diskReservedByOthersBytes')}
    if child:
        lease.mark_launching()
        process = subprocess.Popen(['/bin/sleep', '120'], start_new_session=True)
        from studio.native_owned_processes import read_processes
        row = read_processes()[process.pid]
        lease.record_processes([{'pid': row.pid, 'started': row.started, 'pgid': row.pgid}])
        info['child'] = process.pid
    emit(**info)
    time.sleep(seconds)
    lease.complete()
    lease.close()
    emit(event='completed', nonce=lease.nonce, at=time.time())


def queue(lane: str, project: str) -> None:
    """Try once and report the refusal (ticket kept) or the admission, then wait to be killed."""
    request = pool.PoolRequest(lane, project)
    try:
        lease = work.NativeWorkLease.acquire(lane, project, request=request)
    except work.NativeWorkBusy as error:
        emit(event='queued', sequence=request.sequence, reason=str(error))
    else:
        emit(event='admitted', nonce=lease.nonce, mode=lease.admission['mode'])
    time.sleep(120)


def legacy(project: str) -> None:
    """Run the unmodified baseline lease code against the same namespace."""
    sys.path.insert(0, str(HERE.parent))
    import legacy_native_work_lease_66a7d9a as old
    old.state_root = work.state_root
    try:
        lease = old.NativeWorkLease.acquire('heavy', project)
    except old.NativeWorkBusy as error:
        emit(event='legacy-refused', reason=str(error))
        return
    emit(event='legacy-admitted', nonce=lease.record['nonce'])
    lease.complete()
    lease.close()


CHILD = """
import subprocess, sys, time
blob = bytearray(64 * 1024 * 1024)
for index in range(0, len(blob), 4096):
    blob[index] = 1
grandchild = subprocess.Popen(['/bin/sleep', '1'])
time.sleep(float(sys.argv[1]))
grandchild.wait()
open(sys.argv[2], 'wb').write(b'TEST synthetic owner output; not media')
"""


DISK_CHILD = """
import json, os, sys, time, uuid
request, receipt, size, go, hold, output = sys.argv[1:7]
open(os.path.join(os.path.dirname(request), 'TEST-ready'), 'w').close()
while not os.path.exists(go):
    time.sleep(.05)
ident = uuid.uuid4().hex
with open(request + '.pending', 'w') as handle:
    json.dump({'schemaVersion': 1, 'id': ident,
               'directories': [{'path': os.path.dirname(request), 'bytes': int(size)}]}, handle)
os.rename(request + '.pending', request)
grant = None
for _ in range(600):
    grant = json.load(open(receipt)).get('diskGrant')
    if grant and grant['id'] == ident and grant['status'] != 'waiting':
        break
    time.sleep(.05)
if not grant or grant['status'] != 'granted':
    sys.exit(5)
time.sleep(float(hold))
open(output, 'wb').write(b'TEST synthetic owner output; not media')
"""


JS_CHILD = """
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const [module, cache, attempt, receipt, output] = process.argv.slice(2);
const {requestLongDiskGrant} = await import(pathToFileURL(module).href);
const grant = await requestLongDiskGrant({cache, output: attempt},
  {filesystems: {cache: 2 * 1024 ** 3, output: 1024 ** 3}}, {SNIPER_NATIVE_EXPORT_OWNER: receipt}, 60000);
fs.writeFileSync(output, JSON.stringify(grant));
"""


def run_owner(lane: str, root: Path, command: list[str], expansion: bool = False) -> None:
    """Run one real NativeRun owner (admission, sampling, cleanup) over a TEST child.

    The owner's output path is appended to `command`; `expansion` sets disk_expansion.
    """
    from studio.native_run import NativeRun
    from studio.native_run_config import NativeRunConfig
    from studio.native_runtime import digest
    project, cli, sandbox = root / 'project', root / 'cli.js', root / 'sandbox.sb'
    project.mkdir()
    cli.write_text('TEST synthetic SDK stand-in')
    sandbox.write_text('TEST synthetic sandbox stand-in')
    output = root / 'result.bin'
    settings = NativeRunConfig(project, root, cli, [*command, str(output)], {'PATH': '/usr/bin:/bin'},
                               {'output': str(output), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
                               sandbox=sandbox, deadline=180, capacity_wait_seconds=120, lane=lane,
                               success_status='TEST synthetic owner complete', disk_expansion=expansion)
    run = NativeRun(f'TEST-{lane}', settings)
    emit(event='owner-started', receipt=str(run.path), pid=os.getpid())
    success = run.execute()
    emit(event='owner-finished', success=success, receipt=str(run.path))


def owner(lane: str, attempt: str, seconds: str) -> None:
    """A real owner over the resident-memory TEST child."""
    run_owner(lane, Path(attempt), [sys.executable, '-c', CHILD, seconds])


def disk_owner(attempt: str, size: str, free: str, go: str, hold: str, wait: str) -> None:
    """A real Long-style owner whose TEST child asks it to grow its disk reservation on 'go'."""
    import studio.native_run_disk as served
    from studio.native_run_disk import disk_request_path
    fixed_free(free)
    served.DISK_WAIT_SECONDS = float(wait)  # TEST window; production keeps its constant
    root = Path(attempt)
    receipt = root / 'TEST-heavy.render.json'
    run_owner('heavy', root, [sys.executable, '-c', DISK_CHILD, str(disk_request_path(receipt)), str(receipt),
                              size, go, hold], expansion=True)


def js_disk_owner(attempt: str, cache: str, node: str) -> None:
    """A real owner whose child is the production JS requestLongDiskGrant (TEST sizes: 2 + 1 GiB)."""
    root = Path(attempt)
    child = root.parent / f'{root.name}-child.mjs'
    child.write_text(JS_CHILD)
    module = HERE.parents[2] / 'studio/native_long_sources.mjs'
    run_owner('heavy', root, [node, str(child), str(module), cache, str(root),
                              str(root / 'TEST-heavy.render.json')], expansion=True)


def main(extra: dict | None = None) -> None:
    """Dispatch: <command> <root> <record|-> [arguments]; `extra` adds commands taking the arguments."""
    command, root, record, *rest = sys.argv[1:]
    isolate(root, record)
    commands = {'hold': lambda: hold(rest[0], rest[1], float(rest[2]), rest[3:]),
                'queue': lambda: queue(rest[0], rest[1]), 'legacy': lambda: legacy(rest[0]),
                'owner': lambda: owner(rest[0], rest[1], rest[2]),
                'expand': lambda: expand(*rest[:5]), 'admit-disk': lambda: admit_disk(*rest[:4]),
                'disk-owner': lambda: disk_owner(*rest[:6]), 'js-disk-owner': lambda: js_disk_owner(*rest[:3]),
                **{name: (lambda run=run: run(*rest)) for name, run in (extra or {}).items()}}
    if command not in commands:
        raise SystemExit(f'unknown TEST driver command: {command}')
    commands[command]()


if __name__ == '__main__':
    main()
