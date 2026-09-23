"""Public native entry points must reject skipped or stale prerequisites before media work."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from studio.native_export import export_adapter, validate_export_launch, require_owned_worker, active_owner_snapshot
from studio.native_long_autoresume import recover_automatically
from studio.native_long_prebuild import prebuild_snapshot, require_long_prebuild
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from studio.native_export_history import attempt_reservation, history_directory, known_attempts, register_attempt
from studio.native_short_export import input_pins
from studio.native_run import NativeRun

STUDIO = Path(__file__).resolve().parents[1] / 'studio'


class LaunchEnforcementTests(unittest.TestCase):
    """Exercise the actual shared admission boundary with tiny non-media test files."""

    def setUp(self) -> None:
        """Construct only the request/owner metadata needed for admission decisions."""
        self.enterContext(patch('graphics.visual_source_project.admit_project_sources'))
        self.enterContext(patch('studio.native_motion_previews.require_motion_previews'))
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / 'project'; self.project.mkdir()
        (self.project / 'index.html').write_text('TEST authored project, not rendered')
        (self.project / 'LONG-PROJECT.json').write_text('{}')
        self.output = self.root / 'attempt'; self.output.mkdir()
        self.runtime = self.root / 'runtime'; (self.runtime / 'dist').mkdir(parents=True)
        self.cli = self.runtime / 'dist/cli.js'; self.cli.write_text('TEST SDK')
        self.worker = STUDIO / 'native_long_worker.py'
        self.file = self.output / 'export-request.json'
        self.request = {'adapter': 'native-long', 'project': str(self.project), 'output': str(self.output),
                        'runtime': str(self.runtime), 'tools': {}}
        self.file.write_text(json.dumps(self.request))
        (self.output / 'sample-qc').mkdir()
        (self.output / 'sample-qc/result.json').write_text('{"passed":true}')

    def settings(self, phase: str = 'picture') -> NativeRunConfig:
        """Build the exact production worker command without launching it."""
        sandbox = STUDIO / 'native_localhost_only.sb'
        output = {'picture': 'picture.mp4', 'render': 'review.mp4', 'capture': 'native-frames.json', 'verify': 'checks.json'}[phase]
        return NativeRunConfig(self.project, self.output, self.cli,
            ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(self.worker), str(self.file), phase],
            {}, {'output': str(self.output / output), 'sdkSha256': digest(self.cli), 'sandboxSha256': digest(sandbox)},
            additional_pins={str(self.file): digest(self.file), str(self.worker): digest(self.worker)})

    def test_all_shared_long_phases_admit(self) -> None:
        """Capture, picture, delivery and verification use the same closed launch route."""
        for phase in ('capture', 'picture', 'render', 'verify'):
            self.assertEqual(validate_export_launch(self.settings(phase)), self.request)

    def test_dated_wrapper_cannot_reuse_valid_metadata(self) -> None:
        """A valid SDK digest is insufficient to authorize an alternate render command."""
        settings = self.settings()
        settings.command[4] = str(self.root / 'run_assembly.py')
        with self.assertRaisesRegex(ValueError, 'shared export worker'):
            validate_export_launch(settings)

    def test_missing_manifest_and_ambiguous_project_cannot_select_legacy(self) -> None:
        """Removing a declaration cannot turn native HTML into an unguarded export."""
        (self.project / 'LONG-PROJECT.json').unlink()
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            validate_export_launch(self.settings())
        (self.project / 'LONG-PROJECT.json').write_text('{}')
        (self.project / 'SHORT-PROJECT.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            export_adapter(self.project)

    def test_failed_samples_and_changed_request_stop_launch(self) -> None:
        """Proof must still pass at the shared boundary after preparation."""
        settings = self.settings()
        (self.output / 'sample-qc/result.json').write_text('{"passed":false}')
        with self.assertRaisesRegex(ValueError, 'encoded seam'):
            validate_export_launch(settings)
        self.file.write_text(json.dumps({**self.request, 'output': str(self.root)}))
        with self.assertRaisesRegex(ValueError, 'does not bind'):
            validate_export_launch(settings)

    def test_direct_worker_has_no_implicit_authority(self) -> None:
        """Calling an internal worker directly cannot omit its owner."""
        with patch.dict('os.environ', {}, clear=True), self.assertRaisesRegex(ValueError, 'supervisor'):
            require_owned_worker(self.request)

    def test_owner_updates_publish_whole_snapshots_and_never_replace_an_unowned_receipt(self) -> None:
        """The launch guard can read the complete previous owner during the next write."""
        owner = NativeRun.__new__(NativeRun); owner.path = self.root / 'owner.json'
        owner.receipt_owned = False; owner.result = {'status': 'preparing'}; owner.persist(initial=True)
        from cut_preview_io import write_new
        def observe_pending(file: Path, value: dict) -> None:
            """Observe the final name while only the temporary snapshot is being written."""
            self.assertEqual(json.loads(owner.path.read_text()), {'status': 'preparing'})
            write_new(file, value)
        owner.result = {'status': 'running', 'payload': 'TEST complete snapshot'}
        with patch('studio.native_run.write_new', side_effect=observe_pending):
            owner.persist()
        self.assertEqual(json.loads(owner.path.read_text()), owner.result)
        owner.receipt_owned = False
        with self.assertRaises(FileExistsError): owner.persist()

    def test_owner_snapshot_retries_only_atomic_replacement_and_is_bounded(self) -> None:
        """A changed inode may be reread; arbitrary broken JSON never becomes implicit approval."""
        changed = RuntimeError('cut preview artifact changed during read')
        with patch('studio.native_export.bound_json', side_effect=[changed, {'status': 'running'}]) as read:
            self.assertEqual(active_owner_snapshot(self.file), {'status': 'running'})
            self.assertEqual(read.call_count, 2)
        with patch('studio.native_export.bound_json', side_effect=changed) as read, self.assertRaises(RuntimeError):
            active_owner_snapshot(self.file)
        self.assertEqual(read.call_count, 3)
        with patch('studio.native_export.bound_json', side_effect=RuntimeError('unsafe file')) as read, self.assertRaises(RuntimeError):
            active_owner_snapshot(self.file)
        self.assertEqual(read.call_count, 1)


class AutomaticRecoveryTests(unittest.TestCase):
    """Discovery selects only exact compatible terminal attempts and propagates failed proofs."""

    def setUp(self) -> None:
        """Mock the existing seal reader only after exercising real filesystem discovery."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.current = {'adapter': 'native-long', 'project': '/TEST/project', 'output': str(self.root / 'next'),
                        'runtime': '/TEST/runtime', 'tools': {}, 'audioProfile': 'default-v3',
                        'cache': '/TEST/cache', 'pins': {'/TEST/source': 'a' * 64}}

    def attempt(self, name: str, **changes: object) -> Path:
        """Create explicitly fictional metadata; no claim of real completed media."""
        root = self.root / name; root.mkdir()
        (root / 'export-request.json').write_text(json.dumps({**self.current, 'output': str(root), **changes}))
        (root / 'delivery.json').write_text(json.dumps({'status': 'failed', 'completedAt': '2026-09-16T12:00:00Z'}))
        (root / 'picture-stage.json').write_text('{}')
        return root

    def test_picture_failure_is_recovered_without_a_flag(self) -> None:
        """An ordinary invocation discovers and validates its earlier picture stage."""
        previous = self.attempt('previous')
        with patch('studio.native_long_autoresume.prepare_picture_recovery', return_value=self.current) as recover:
            result = recover_automatically(self.current)
        recover.assert_called_once_with(self.current, previous)
        self.assertEqual(result['recoverySelection']['reused'], 'picture-and-audio')

    def test_changed_source_policy_and_nonterminal_attempt_do_not_resume(self) -> None:
        """Changed content/policy is fresh work; incomplete owner state is never auto-reclaimed."""
        self.attempt('changed', pins={'/TEST/source': 'b' * 64})
        self.attempt('policy', audioProfile='other')
        with patch('studio.native_long_autoresume.prepare_picture_recovery') as recover:
            result = recover_automatically(self.current)
        recover.assert_not_called()
        self.assertEqual(result['recoverySelection']['mode'], 'fresh')

    def test_incomplete_compatible_attempt_blocks_duplicate_work(self) -> None:
        """An in-flight or uncertain owner requires reconciliation, never a fresh duplicate."""
        unfinished = self.attempt('unfinished'); (unfinished / 'delivery.json').unlink()
        with self.assertRaisesRegex(ValueError, 'active or interrupted'):
            recover_automatically(self.current)

    def test_matching_corrupt_seal_fails_instead_of_silently_rerendering(self) -> None:
        """An invalid selected proof remains actionable; discovery must not swallow it."""
        self.attempt('corrupt')
        with patch('studio.native_long_autoresume.prepare_picture_recovery', side_effect=ValueError('changed seal')), \
                self.assertRaisesRegex(ValueError, 'changed seal'):
            recover_automatically(self.current)

    def test_complete_media_wins_over_picture_and_search_is_bounded(self) -> None:
        """Reuse the most complete valid stage without crawling the workspace."""
        self.attempt('picture')
        finished = self.attempt('finished'); (finished / 'render-stage.json').write_text('{}')
        with patch('studio.native_long_autoresume.prepare_render_recovery', return_value=self.current) as recover:
            recover_automatically(self.current)
        recover.assert_called_once_with(self.current, finished)
        with patch('studio.native_export_history.MAX_HISTORY', 1), self.assertRaisesRegex(ValueError, 'exceeds'):
            recover_automatically(self.current)


class PrebuildEnforcementTests(unittest.TestCase):
    """Long review binds actual project bytes without hashing itself."""

    def test_missing_review_stops_before_validator_or_tools(self) -> None:
        """No source extraction or validator process can precede required evidence."""
        with tempfile.TemporaryDirectory() as root, patch('subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'PREBUILD-REVIEW'):
                require_long_prebuild(Path(root), {}, {})
            run.assert_not_called()

    def test_media_change_stales_review_but_adding_receipt_has_no_cycle(self) -> None:
        """The binding includes complete media as well as HTML and timeline declarations."""
        with tempfile.TemporaryDirectory() as root:
            project = Path(root).resolve()
            media = project / 'source.mp4'; media.write_bytes(b'TEST picture')
            original = prebuild_snapshot(project)['planHash']
            (project / 'PREBUILD-REVIEW.json').write_text('{}')
            self.assertEqual(prebuild_snapshot(project)['planHash'], original)
            media.write_bytes(b'TEST different picture')
            self.assertNotEqual(prebuild_snapshot(project)['planHash'], original)

    def test_review_evidence_cannot_replace_an_earlier_project_hash(self) -> None:
        """Mutation during validator execution must not be relabeled as the reviewed snapshot."""
        with tempfile.TemporaryDirectory() as root:
            project = Path(root).resolve(); media = project / 'source.mp4'; media.write_bytes(b'TEST before')
            (project / 'PREBUILD-REVIEW.json').write_text('{}')
            snapshot = prebuild_snapshot(project)
            def changed_validator(*args: object, **kwargs: object) -> SimpleNamespace:
                """Model a racing changed source referenced by review evidence."""
                media.write_bytes(b'TEST changed during validation')
                return SimpleNamespace(stdout=json.dumps({'planHash': snapshot['planHash'],
                    'evidence': [{'path': str(media), 'sha256': digest(media)}]}))
            with patch('graphics.visual_source_project.admit_project_sources'), \
                    patch('studio.native_long_prebuild.subprocess.run', side_effect=changed_validator), \
                    self.assertRaisesRegex(ValueError, 'evidence conflicts'):
                require_long_prebuild(project, {'node': 'TEST node'}, {})

    def test_short_review_external_evidence_remains_bound_after_cli_validation(self) -> None:
        """An external critic file changed after validation cannot acquire a fresh accepted hash."""
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root).resolve(); project = parent / 'project'; project.mkdir()
            evidence = parent / 'evidence.txt'; evidence.write_text('TEST review')
            receipt = parent / 'review.json'
            receipt.write_text(json.dumps({'evidence': [{'path': str(evidence), 'sha256': digest(evidence)}]}))
            plan = {'prebuildReview': {'path': str(receipt), 'sha256': digest(receipt)},
                    'assets': [], 'strategy': {'schemaVersion': 2},
                    'canvas': {'frameRate': '25/1', 'totalFrames': 25}}
            (project / 'SHORT-PROJECT.json').write_text(json.dumps(plan))
            (project / 'PROJECT-MANIFEST.json').write_text('{"files":[]}')
            pins = input_pins(project, project / 'runtime', {})
            self.assertEqual(pins[str(evidence)], digest(evidence))
            self.assertEqual(pins[str(receipt)], digest(receipt))
            evidence.write_text('TEST changed review')
            with self.assertRaisesRegex(ValueError, 'changed before pinning'):
                input_pins(project, project / 'runtime', {})


class AttemptHistoryTests(unittest.TestCase):
    """Discovery survives a different output parent but never trusts changed pointers."""

    def setUp(self) -> None:
        """Use private isolated history and a fictional immutable export request."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.attempt = self.root / 'earlier'; self.attempt.mkdir()
        self.request = {'project': str(self.root / 'project'), 'output': str(self.attempt),
                        'runtime': str(self.root / 'runtimes/version/hyperframes')}
        (self.attempt / 'export-request.json').write_text(json.dumps(self.request))

    def test_cross_parent_discovery_and_changed_request_rejection(self) -> None:
        """The pointer is discovery only; original request integrity remains mandatory."""
        with attempt_reservation(self.request):
            register_attempt(self.request)
        current = {**self.request, 'output': str(self.root / 'elsewhere/new')}
        self.assertEqual(known_attempts(current), [self.attempt])
        (self.attempt / 'export-request.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'history changed'):
            known_attempts(current)

    def test_history_bound_excludes_lock_and_never_overflows(self) -> None:
        """One allowed attempt stays discoverable; the second fails before its pointer write."""
        with patch('studio.native_export_history.MAX_HISTORY', 1), attempt_reservation(self.request):
            register_attempt(self.request)
            self.assertEqual(known_attempts(self.request), [self.attempt])
            next_attempt = self.root / 'next'; next_attempt.mkdir()
            (next_attempt / 'export-request.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'history is full'):
                register_attempt({**self.request, 'output': str(next_attempt)})
        self.assertEqual(len(list(history_directory(self.request).glob('*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
