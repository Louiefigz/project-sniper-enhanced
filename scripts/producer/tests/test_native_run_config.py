"""Fail shared native work at admission, before acquiring a lease or launching tools."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest


class NativeRunConfigTests(unittest.TestCase):
    """Use local text fixtures only; no browser, encoder, resource probe or real lease."""

    def setUp(self) -> None:
        """Provide the same metadata shape used by Shorts and public web capture."""
        temporary = tempfile.TemporaryDirectory(prefix='native-admission-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project, self.output = self.root / 'project', self.root / 'output'
        self.project.mkdir()
        self.output.mkdir()
        self.cli, self.sandbox = self.root / 'cli.js', self.root / 'sandbox.sb'
        self.cli.write_text('TEST executable fixture')
        self.sandbox.write_text('TEST sandbox fixture')
        self.admission = {'output': str(self.output / 'result.json'),
                          'sdkSha256': digest(self.cli), 'sandboxSha256': digest(self.sandbox)}
        self.settings = NativeRunConfig(self.project, self.output, self.cli,
                                       ['TEST-NO-LAUNCH'], {}, self.admission, sandbox=self.sandbox)
        self.acquire = self.enterContext(patch('studio.native_run.NativeWorkLease.acquire'))
        self.launch = self.enterContext(patch('studio.native_run.subprocess.Popen'))
        self.read = self.enterContext(patch('studio.native_measurement_retry.read_snapshot'))

    def assert_rejected(self, admission: object, message: str) -> None:
        """Invalid settings cannot enter the shared owner lifecycle."""
        with self.assertRaisesRegex(ValueError, message):
            NativeRun('invalid', replace(self.settings, admission=admission)).execute()
        self.acquire.assert_not_called()
        self.launch.assert_not_called()
        self.read.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_missing_required_fields_fail_before_heavy_work(self) -> None:
        """Omitted digest metadata must not fail during closeout after completed work."""
        for key in self.admission:
            with self.subTest(key=key):
                self.assert_rejected({name: value for name, value in self.admission.items() if name != key}, key)

    def test_non_mapping_admission_is_rejected_consistently(self) -> None:
        """Malformed task-local callers receive a bounded configuration error."""
        for value in (None, [], 'metadata', 42):
            with self.subTest(value=value):
                self.assert_rejected(value, 'metadata mapping')

    def test_malformed_digest_is_rejected_for_both_pins(self) -> None:
        """Canonical digest syntax rejects wrong types, lengths, whitespace and hex."""
        invalid = (None, 42, '', 'a' * 63, 'a' * 65, 'g' * 64, 'A' * 64, ' ' + 'a' * 63)
        for key, value in ((key, value) for key in ('sdkSha256', 'sandboxSha256') for value in invalid):
            with self.subTest(key=key, value=value):
                self.assert_rejected({**self.admission, key: value}, key)

    def test_stale_digest_is_rejected_before_heavy_work(self) -> None:
        """Well-formed metadata must bind the bytes that the attempt will actually use."""
        for key in ('sdkSha256', 'sandboxSha256'):
            with self.subTest(key=key):
                self.assert_rejected({**self.admission, key: '0' * 64}, 'does not match the current file')

    def test_invalid_output_is_rejected_consistently(self) -> None:
        """Require a usable absolute file target before resource measurements begin."""
        invalid = (None, 42, self.output / 'result.json', '', ' ', 'relative.mp4',
                   str(self.output), str(self.output / 'missing' / 'result.json'), '/bad\x00path',
                   str(self.output / 'not-a-file') + '/')
        for value in invalid:
            with self.subTest(value=value):
                self.assert_rejected({**self.admission, 'output': value}, 'output')

    def test_symlink_output_and_parent_file_are_rejected(self) -> None:
        """Output qualification cannot follow a preexisting or broken leaf symlink."""
        target = self.root / 'existing.txt'
        target.write_text('TEST previous file')
        link = self.root / 'linked-output'
        link.symlink_to(target)
        broken = self.root / 'broken-output'
        broken.symlink_to(self.root / 'absent')
        for path in (link, broken, target / 'result.json'):
            with self.subTest(path=path):
                self.assert_rejected({**self.admission, 'output': str(path)}, 'output')
        self.assertEqual(target.read_text(), 'TEST previous file')

    def test_missing_executable_or_sandbox_is_a_configuration_error(self) -> None:
        """Missing executable bytes are reported before the heavy lane is acquired."""
        for field in ('cli', 'sandbox'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'file is unreadable'):
                replace(self.settings, **{field: self.root / 'absent'})
        self.acquire.assert_not_called()
        self.launch.assert_not_called()
        self.read.assert_not_called()

    def test_existing_and_new_shared_output_formats_are_admitted(self) -> None:
        """JSON evidence and MP4 delivery share metadata validation without mode branches."""
        paths = (self.output / 'review.mp4', self.output / 'capture.json',
                 self.root / 'checkpoint.json', self.root / 'existing.json')
        paths[-1].write_text('TEST existing verification artifact')
        for path in paths:
            with self.subTest(path=path):
                settings = replace(self.settings, admission={**self.admission, 'output': str(path)})
                self.assertEqual(NativeRun('valid', settings).result['output'], str(path))
        self.acquire.assert_not_called()
        self.launch.assert_not_called()
        self.read.assert_not_called()

    def test_constructor_copies_metadata_from_the_caller(self) -> None:
        """An adapter cannot alter a prepared config by mutating its original mapping."""
        self.admission.clear()
        self.settings.validate_admission()
        self.assertIn('sandboxSha256', self.settings.admission)

    def test_owner_revalidates_metadata_before_hashing_project_files(self) -> None:
        """A mutable config cannot bypass admission by changing after construction."""
        self.settings.admission.pop('sdkSha256')
        with patch('studio.native_run.owner_file_pins') as pins:
            with self.assertRaisesRegex(ValueError, 'sdkSha256'):
                NativeRun('invalid', self.settings)
        pins.assert_not_called()
        self.acquire.assert_not_called()
        self.launch.assert_not_called()

    def test_prepare_rejects_mutated_metadata_and_persists_failure(self) -> None:
        """Late metadata loss fails with a receipt, not a secondary closeout KeyError."""
        run = NativeRun('invalid', self.settings)
        self.settings.admission.pop('sandboxSha256')
        with patch('builtins.print'):
            self.assertFalse(run.execute())
        receipt = json.loads(run.path.read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertIn('sandboxSha256', receipt['abortReason'])
        self.assertTrue(receipt['cleanup']['childNeverLaunched'])
        self.acquire.assert_not_called()
        self.launch.assert_not_called()
        self.read.assert_not_called()

    def test_prepare_rejects_changed_pinned_bytes_before_lease(self) -> None:
        """Files changed after config validation cannot run under obsolete admission."""
        run = NativeRun('invalid', self.settings)
        self.sandbox.write_text('TEST changed sandbox bytes')
        with patch('builtins.print'):
            self.assertFalse(run.execute())
        self.assertIn('sandboxSha256 does not match', json.loads(run.path.read_text())['abortReason'])
        self.acquire.assert_not_called()
        self.launch.assert_not_called()
        self.read.assert_not_called()

    def test_prepare_rejects_valid_metadata_redirect_after_owner_binding(self) -> None:
        """A valid replacement path cannot silently redirect the owner's bound output."""
        run = NativeRun('invalid', self.settings)
        self.settings.admission['output'] = str(self.output / 'redirected.json')
        with patch('builtins.print'):
            self.assertFalse(run.execute())
        receipt = json.loads(run.path.read_text())
        self.assertEqual(receipt['output'], self.admission['output'])
        self.assertIn('admission changed', receipt['abortReason'])
        self.acquire.assert_not_called()
        self.launch.assert_not_called()
        self.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
