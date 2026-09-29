"""Supervisor-side source-store hooks: owner-lock lifetime, Node parity and the bounded view step."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio import native_source_store as store

REPO = Path(__file__).resolve().parents[3]
NODE_STORE = REPO / 'scripts/producer/studio/native_source_store.mjs'
STORE_CHILD = REPO / 'scripts/tests/native_source_store_child.mjs'
HOLD_OWNER = ('import sys,time; sys.path.insert(0, sys.argv[1]); from pathlib import Path; '
              'from studio.native_source_store import hold_source_store_owner as hold; '
              'print(hold(Path(sys.argv[2])), flush=True); time.sleep(60)')


def probe(file: Path) -> str:
    """Probe with a separate open file description, exactly as collection does."""
    descriptor = os.open(file, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return 'exited'
    except BlockingIOError:
        return 'live'
    finally:
        os.close(descriptor)


class SourceStoreOwnerTests(unittest.TestCase):
    """Real kernel locks and processes; no media."""

    def setUp(self) -> None:
        """Use a canonical private cache root per test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache = Path(temporary.name).resolve() / 'cache'
        self.cache.mkdir()

    def test_owner_lock_is_held_for_this_process_and_published_only_when_locked(self) -> None:
        """The returned owner is final, private and already locked; no creation stub remains."""
        owner = Path(store.hold_source_store_owner(self.cache))
        self.assertEqual(owner.parent, self.cache / store.STORE_NAME / 'owners')
        self.assertEqual(owner.suffix, '.lock')
        self.assertEqual(probe(owner), 'live')
        self.assertEqual([path.name for path in owner.parent.iterdir()], [owner.name])
        self.assertEqual(owner.parent.stat().st_mode & 0o777, 0o700)

    def test_owner_lock_is_released_by_the_kernel_when_the_supervisor_exits(self) -> None:
        """A killed supervisor cannot leave a lease owner that looks alive (no PID reuse)."""
        child = subprocess.Popen([sys.executable, '-c', HOLD_OWNER, str(REPO / 'scripts/producer'), str(self.cache)],
                                 stdout=subprocess.PIPE, text=True)
        try:
            owner = Path(child.stdout.readline().strip())
            self.assertEqual(probe(owner), 'live')
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        self.assertEqual(probe(owner), 'exited')

    def test_view_path_matches_the_node_store_derivation(self) -> None:
        """Python passes the same private view to the SDK that Node leases and links."""
        request = {'cache': str(self.cache), 'output': '/TEST/attempt-01'}
        script = (f"import {{openSourceStore,storeViewPath}} from '{NODE_STORE.as_uri()}';"
                  f"console.log(storeViewPath(openSourceStore({json.dumps(str(self.cache))}),'/TEST/attempt-01'));")
        node = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
        self.assertEqual(node.stdout.strip(), str(store.source_view_path(request)))

    def test_view_step_is_bounded_by_the_owner_and_verifies_its_published_view(self) -> None:
        """An exhausted owner never launches the step; a foreign result is refused."""
        owner = self.cache.parent / 'pipeline.render.json'
        started = datetime.now(timezone.utc) - timedelta(seconds=599)
        owner.write_text(json.dumps({'startedAt': started.isoformat(), 'runDeadlineSeconds': 600}))
        environment = {'SNIPER_NATIVE_EXPORT_OWNER': str(owner)}
        with mock.patch.dict(os.environ, environment), self.assertRaisesRegex(Exception, 'deadline is exhausted'):
            store.owner_remaining_seconds()
        owner.write_text(json.dumps({'startedAt': datetime.now(timezone.utc).isoformat(), 'runDeadlineSeconds': 600}))
        with mock.patch.dict(os.environ, environment):
            self.assertGreater(store.owner_remaining_seconds(), 500)
        output = self.cache.parent / 'attempt'
        (output / 'render-source-view').mkdir(parents=True)
        request = {'cache': str(self.cache), 'output': str(output), 'tools': {'node': 'TEST node'}}
        (output / 'render-source-view/source-view.json').write_text(json.dumps(
            {'status': store.VIEW_STATUS, 'view': str(self.cache / 'another-view')}))
        with mock.patch.object(store.subprocess, 'run') as run, self.assertRaisesRegex(Exception, 'did not publish this attempt view'):
            store.prepare_source_view(request, timeout=5)
        self.assertEqual(run.call_args.kwargs['timeout'], 5)


class SupervisorLeaseIntegrityTests(unittest.TestCase):
    """The export supervisor's owner lock governs replacement of a refused shared entry (TEST frames)."""

    def setUp(self) -> None:
        """Private cache, a TEST deadline owner and identical source bytes for every revision folder."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.deadline = self._deadline('owner.render.json', 600)

    def _deadline(self, name: str, remaining: float) -> Path:
        """A TEST owner record whose source-frame waits end about ``remaining`` seconds from now."""
        started = datetime.now(timezone.utc) - timedelta(seconds=570 - remaining)
        record = self.root / name
        record.write_text(json.dumps({'startedAt': started.isoformat(), 'runDeadlineSeconds': 600}))
        return record

    def _spec(self, label: str, owner: str | None = None) -> dict:
        """One TEST acquisition of the same content from a fresh revision folder."""
        project = self.root / f'project-{label}'
        (project / 'assets').mkdir(parents=True)
        source = project / 'assets/source.mp4'
        source.write_text('TEST identical source bytes for every revision')
        spec = {'label': label, 'project': str(project), 'cache': str(self.cache), 'events': str(self.root / 'events.jsonl'),
                'output': str(self.root / f'attempt-{label}'), 'work': str(self.root / f'work-{label}'), 'rate': 25,
                'totalFrames': 50, 'runtimeLibrarySha256': '1' * 64, 'frameDelayMs': 0,
                'tools': {'ffmpeg': 'TEST ffmpeg', 'ffprobe': 'TEST ffprobe'},
                'pins': {str(source): hashlib.sha256(source.read_bytes()).hexdigest(), 'TEST ffmpeg': '2' * 64,
                         'TEST ffprobe': '3' * 64},
                'videos': [{'id': 'source-0-0', 'src': 'assets/source.mp4', 'mediaStart': 0, 'start': 0, 'end': 1}]}
        return {**spec, 'sourceStoreOwner': owner} if owner else spec

    def _acquire(self, spec: dict, deadline: Path | None = None) -> dict:
        """Run the Node store child (fake SDK decoder) and return its exit code and final JSON line."""
        environment = {**os.environ, 'SNIPER_NATIVE_EXPORT_OWNER': str(deadline or self.deadline)}
        done = subprocess.run(['node', str(STORE_CHILD), json.dumps(spec)], capture_output=True, text=True,
                              env=environment, timeout=60, check=False)
        line = [row for row in done.stdout.splitlines() if row.startswith('{')][-1]
        return {'code': done.returncode, 'stdout': done.stdout, **json.loads(line)}

    def test_supervisor_lease_keeps_a_refused_linked_entry_until_the_supervisor_exits(self) -> None:
        """A corrupted entry the live supervisor's view links is neither served nor replaced; exit frees it."""
        supervisor = subprocess.Popen([sys.executable, '-c', HOLD_OWNER, str(REPO / 'scripts/producer'), str(self.cache)],
                                      stdout=subprocess.PIPE, text=True)
        try:
            owner = supervisor.stdout.readline().strip()
            held = self._acquire(self._spec('capture', owner))
            self.assertEqual(held['code'], 0, held)
            frame = Path(held['entries'][0]['entry']) / 'frame_00002.png'
            size = frame.stat().st_size
            frame.chmod(0o644)
            frame.write_bytes(b'X' * size)
            blocked = self._acquire(self._spec('blocked'), self._deadline('short.render.json', 1.5))
            self.assertEqual(blocked['code'], 1)
            self.assertIn('waiting for them within the caller deadline', blocked['stdout'])
            self.assertIn('frame bytes differ from the published frame digest', blocked['error'])
            self.assertIn('so it was neither served nor replaced before the caller deadline', blocked['error'])
            self.assertEqual(frame.read_bytes(), b'X' * size)
        finally:
            supervisor.kill()
            supervisor.wait(timeout=5)
            supervisor.stdout.close()
        after = self._acquire(self._spec('after'))
        self.assertEqual(after['code'], 0, after)
        self.assertEqual(after['entries'][0]['outcome'], 'published-by-this-job')
        self.assertIn('frame bytes differ', after['entries'][0]['replaced']['reason'])
        self.assertEqual(after['entries'][0]['frameDigest'], held['entries'][0]['frameDigest'])


if __name__ == '__main__':
    unittest.main()
