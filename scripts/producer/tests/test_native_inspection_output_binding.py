"""Successful owner finalization binds exact JSON bytes; no real media/owner runs occur."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from studio.native_run_lifecycle import bind_completed_output


class InspectionOutputBindingTests(unittest.TestCase):
    """Exercise the real finish path with a completed fictional child and actual files."""

    def setUp(self) -> None:
        """Set up bounded JSON output and actual executable/source pin checks."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        project = self.root / 'project'
        project.mkdir()
        (project / 'index.html').write_text('TEST source')
        cli, sandbox = self.root / 'cli.js', self.root / 'sandbox.sb'
        cli.write_text('TEST CLI')
        sandbox.write_text('TEST sandbox')
        self.file = self.root / 'result.json'
        self.file.write_text('{"TEST":"completed"}')
        self.settings = NativeRunConfig(project, self.root, cli, ['TEST-no-launch'], {},
            {'output': str(self.file), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
            sandbox=sandbox, output_digest_limit=4096)
        self.enterContext(patch('studio.native_run.owner_file_pins', return_value={}))
        self.enterContext(patch('builtins.print'))

    def owner(self, settings: NativeRunConfig | None = None) -> NativeRun:
        """Construct finalization state only; it does not represent a measured execution."""
        owner = NativeRun('inspection', settings or self.settings)
        owner.child = Mock(returncode=0)
        owner.child.poll.return_value = 0
        owner.result.update(exitCode=0, cleanup={'verified': True, 'survivors': []}, leaseCleanupVerified=True)
        return owner

    def test_success_receipt_contains_owner_digest_before_first_publication(self) -> None:
        """The digest is computed by finish after successful child and cleanup checks."""
        owner = self.owner()
        owner.finish()
        result = json.loads(owner.path.read_text())
        self.assertEqual(result['status'], self.settings.success_status)
        self.assertEqual(result['completedOutput'], {'path': str(self.file), 'sha256': digest(self.file),
                                                    'bytes': self.file.stat().st_size})

    def test_unverified_cleanup_never_publishes_success_or_output_digest(self) -> None:
        """A visible result from a failed cleanup remains untrusted."""
        owner = self.owner()
        owner.result['cleanup'] = {'verified': False, 'survivors': [123]}
        owner.finish()
        self.assertEqual(owner.result['status'], 'failed')
        self.assertNotIn('completedOutput', owner.result)

    def test_malformed_oversize_and_linked_result_refuse_final_success(self) -> None:
        """Opted-in technical outputs must be bounded canonical JSON objects."""
        for index, payload in enumerate((b'not-json', b'[]', b'x' * 4097)):
            self.file.write_bytes(payload)
            owner = self.owner()
            owner.path = self.root / f'bad-{index}.json'
            owner.finish()
            self.assertEqual(owner.result['status'], 'failed')
            self.assertNotIn('completedOutput', owner.result)
        owner = self.owner()
        self.file.unlink()
        self.file.symlink_to(self.settings.cli)
        self.assertFalse(bind_completed_output(owner, True))

    def test_result_mutation_between_hash_and_json_read_refuses(self) -> None:
        """A fresh caller pin cannot replace bytes captured at the completion boundary."""
        from cut_preview_io import bound_json
        def mutate(file: Path, sha: str, maximum: int) -> dict:
            """Replace the bytes after the completion digest but before its cold read."""
            file.write_text('{"TEST":"replaced"}')
            return bound_json(file, sha, maximum=maximum)
        with patch('cut_preview_io.bound_json', side_effect=mutate):
            owner = self.owner()
            owner.finish()
        self.assertEqual(owner.result['status'], 'failed')

    def test_default_unrelated_owner_keeps_binary_output_behavior(self) -> None:
        """The optional inspection contract does not relabel ordinary media output."""
        self.file.write_bytes(b'TEST arbitrary non-JSON media')
        owner = self.owner(replace(self.settings, output_digest_limit=None))
        owner.finish()
        self.assertEqual(owner.result['status'], self.settings.success_status)
        self.assertNotIn('completedOutput', owner.result)

    def test_digest_limit_is_bounded_integer_before_any_owner_launch(self) -> None:
        """Boolean, zero, negative, unbounded and fractional budgets refuse at configuration."""
        for limit in (True, 0, -1, 16 * 1024 * 1024 + 1, 1.5):
            with self.assertRaisesRegex(ValueError, 'digest limit'):
                replace(self.settings, output_digest_limit=limit)
