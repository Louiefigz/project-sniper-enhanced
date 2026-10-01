"""Shared Studio-manager fixture: real private registry I/O, inert preview identities, no processes."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
import native_work_lease as work
from native_render_resources import GIB, ProcessRequest, parse_snapshot
from test_native_render_resources import raw_sample
from _native_pool_fixture import members
from studio import managed_preview as managed
from studio import managed_preview_launch as launching
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio.studio_server import ServerRecord


class ManagedPreviewFixture:
    """Real private registry I/O with inert preview-process leaves (mixed into a TestCase)."""

    def setUp(self) -> None:
        """Create two native draft folders and isolate all global runtime state."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.projects = [self.root / f'draft-{index}' for index in range(registry.MAX_MANAGED_PREVIEWS + 1)]
        for project in self.projects:
            project.mkdir()
            (project / 'index.html').write_text('<html>TEST native source</html>')
        self.identities = {}
        self.next_pid = 24500
        self.runtime = self.checkout_runtime('checkout-a', 'TEST-identity-a')
        self.cli = str(self.runtime / 'dist/cli.js')
        self.snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        patches = [mock.patch.object(work, 'state_root', return_value=self.root / 'registry'),
                   mock.patch.object(launching, 'read_snapshot', return_value=self.snapshot),
                   mock.patch.object(launching, 'adaptive_admission_reasons',
                                     wraps=launching.adaptive_admission_reasons),
                   mock.patch.object(launching, 'launch_preview', side_effect=self.launch),
                   mock.patch.object(state, 'process_identity', side_effect=lambda pid: self.identities.get(pid)),
                   mock.patch.object(state, 'read_tree_table', side_effect=self.tree),
                   mock.patch.object(managed, 'install_runtime', return_value=self.runtime),
                   mock.patch.object(state, 'read_command_table', side_effect=lambda: list(self.identities.values()))]
        self.mocks = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)

    def checkout_runtime(self, checkout: str, identity: str) -> Path:
        """A checkout's content-addressed runtime directory (nothing in it is executed)."""
        return self.root / checkout / 'templates/motion/.sniper-native-runtime' / identity / 'hyperframes'

    def heavy_fence(self) -> bool:
        """Whether any pool member record remains (since M-056 a startup holds a Studio slot, never a render slot)."""
        return bool(members(self.root / 'registry'))

    def tree(self) -> dict:
        """Expose only inert fixture identities to the real ancestry algorithm."""
        return {pid: (1, row['pgid'], row['started']) for pid, row in self.identities.items()}

    def launch(self, cli: str, project: str, port: int, **options: object) -> ServerRecord:
        """Create an inert exact preview identity; never call subprocess.Popen."""
        self.assertFalse(options['open_browser'])
        self.next_pid += 1
        pid = self.next_pid
        self.identities[pid] = dict(pid=pid, pgid=pid, started='Wed Sep  9 11:00:00 2026',
            command=f'node {cli} preview {project} --port {port} --foreground --json')
        return ServerRecord(port, pid, f'http://127.0.0.1:{port}', 'TEST')

    def record(self, index: int) -> Path:
        """One project's private registry record."""
        return self.root / 'registry' / registry.REGISTRY_DIR / registry.record_name(str(self.projects[index]))

    def open(self, index: int = 0, wait_seconds: float = managed.DEFAULT_WAIT_SECONDS) -> ServerRecord:
        """Use real manager/lease/registry logic for a fixture draft."""
        return managed.open_preview(str(self.projects[index]), 3990 + index, None, wait_seconds)

    def stop_signal(self, pid: int, selected: object) -> None:
        """Simulate only the addressed inert server exiting on its signal."""
        self.identities.pop(pid)
