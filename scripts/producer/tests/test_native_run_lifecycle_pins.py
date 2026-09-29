"""Owner success and final pins, conjunct by conjunct (X132 mi1): the pure lifecycle functions, table-tested.

Stage-5 review mi1: after M-029c moved the inline checks into ``native_run_lifecycle``, removing any single success
conjunct or forcing a stability flag survived every module that references them. These tables pin each one.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from studio.native_run_config import source_hashes
from studio.native_run_lifecycle import owner_succeeded, verify_final_pins
from studio.native_runtime import digest

STABILITY = ('sourceStable', 'sdkStable', 'sandboxStable', 'additionalFilesStable')


class OwnerSuccessAndPinTests(unittest.TestCase):
    """TEST files only; no process is started."""

    def setUp(self) -> None:
        """A project, SDK CLI, sandbox profile and one additional pin, all recorded at admission."""
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.project, self.root = base / 'project', base / 'attempt'
        self.project.mkdir()
        self.root.mkdir()
        (self.project / 'index.html').write_text('<p>TEST composition</p>')
        self.cli, self.sandbox, self.extra = base / 'cli.js', base / 'TEST.sb', base / 'extra.py'
        for file in (self.cli, self.sandbox, self.extra):
            file.write_text(f'TEST {file.name}')
        self.output = self.root / 'output.mp4'
        self.output.write_bytes(b'TEST media')

    def owner(self) -> SimpleNamespace:
        """An owner whose child exited 0 with verified cleanup, before its final pin check."""
        return SimpleNamespace(
            project=self.project, cli=self.cli, settings=SimpleNamespace(sandbox=self.sandbox),
            additional_pins={str(self.extra): digest(self.extra)}, abort_reason=None,
            admission={'sdkSha256': digest(self.cli), 'sandboxSha256': digest(self.sandbox)},
            child=SimpleNamespace(returncode=0), root=self.root, label='TEST',
            result={'sourceHashesBefore': source_hashes(self.project), 'cleanup': {'verified': True},
                    'leaseCleanupVerified': True})

    def test_verify_final_pins_marks_exactly_the_changed_key_unstable(self) -> None:
        """Each pinned input changed after admission clears its own flag and no other."""
        files = dict(zip(STABILITY, (self.project / 'index.html', self.cli, self.sandbox, self.extra)))
        for key, file in files.items():
            owner, original = self.owner(), file.read_text()
            file.write_text('TEST changed after admission')
            verify_final_pins(owner)
            file.write_text(original)
            with self.subTest(changed=key):
                self.assertEqual({name: owner.result[name] for name in STABILITY},
                                 {name: name != key for name in STABILITY})

    def test_owner_succeeds_only_with_every_conjunct(self) -> None:
        """Removing any single conjunct (exit, abort, cleanup, output, a stability flag) is not success."""
        whole = self.owner()
        verify_final_pins(whole)
        self.assertTrue(owner_succeeded(whole, self.output))
        removals = {'no child': lambda owner: setattr(owner, 'child', None),
                    'nonzero exit': lambda owner: setattr(owner, 'child', SimpleNamespace(returncode=1)),
                    'abort reason': lambda owner: setattr(owner, 'abort_reason', 'TEST abort'),
                    'cleanup unverified': lambda owner: owner.result.update(cleanup={'verified': False}),
                    'lease cleanup unrecorded': lambda owner: owner.result.pop('leaseCleanupVerified'),
                    **{key: (lambda owner, key=key: owner.result.update({key: False})) for key in STABILITY}}
        for name, remove in removals.items():
            owner = copy.deepcopy(whole)
            remove(owner)
            with self.subTest(removed=name):
                self.assertFalse(owner_succeeded(owner, self.output))
        self.assertFalse(owner_succeeded(whole, self.root / 'TEST-missing.mp4'))


if __name__ == '__main__':
    unittest.main()
