"""Bounded, source-pinned orchestration of sequential native QC phases."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio.native_runtime import digest
from studio.native_short_worker import capture_checks


class NativeQcPhaseTests(unittest.TestCase):
    """Keep phased verification sequential, source-bound and fail-closed."""

    def setUp(self):
        """Create one current-attempt schedule; no prior partial evidence is used."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.schedule = self.root / 'native-qc-phases/schedule.json'
        self.schedule.parent.mkdir()
        self.schedule.write_text('current schedule')
        compiler = self.schedule.parent / 'plan/compiled/index.html'
        compiler.parent.mkdir(parents=True)
        compiler.write_text('compiled HTML')
        self.compiler_receipt = compiler.parent.parent / 'compiler-result.json'
        self.compiler_receipt.write_text('current compiler result')
        self.compiler_payload = compiler.parent.parent / 'compiler-result.bin'
        self.compiler_payload.write_bytes(b'current compiled payload')
        self.request = {'captureMode': 'cached-native-batches', 'pins': {},
                        'output': str(self.root), 'tools': {'node': '/test/node'}}
        self.planned = {'status': 'native-qc-phases-planned', 'chunkCount': 2,
                        'scheduleSha256': digest(self.schedule),
                        'compilerPins': {str(file): digest(file) for file in
                                         (compiler, self.compiler_receipt, self.compiler_payload)}}

    def phase_child(self, command):
        """Publish distinct child bytes so parent-held digest checks execute in tests."""
        if command[3] == 'plan':
            return json.dumps(self.planned)
        if command[3] == 'chunk':
            index = int(command[4])
            file = self.schedule.parent / f'chunk-{index:03d}/receipt.json'
            file.parent.mkdir()
            file.write_text(f'completed chunk {index}')
            return json.dumps({'status': 'native-qc-chunk-complete', 'index': index,
                               'receiptSha256': digest(file)})
        file = self.root / 'native-frames.json'
        file.write_text('completed aggregate')
        return json.dumps({'status': 'native-references-and-seek-states-pass', 'sha256': digest(file)})

    def test_every_chunk_is_sequential_and_binds_the_same_schedule(self):
        """Two chunks and final aggregation use one plan without resetting an owner."""
        with mock.patch('studio.native_short_worker.run', side_effect=self.phase_child) as run, \
                mock.patch('studio.native_short_worker.verify_files') as verify:
            capture_checks(self.request, self.root / 'export-request.json')
        actions = [call.args[0][3:] for call in run.call_args_list]
        authority = ['--schedule-sha256', self.planned['scheduleSha256']]
        self.assertEqual(actions, [['plan'], ['chunk', '0', *authority],
                                  ['chunk', '1', *authority], ['finish', *authority]])
        self.assertEqual(verify.call_count, 5)

    def test_invalid_chunk_counts_do_not_launch_capture(self):
        """Untrusted planner output cannot create an unbounded or empty loop."""
        for count in (0, 129, True, '2'):
            with self.subTest(count=count), \
                    mock.patch('studio.native_short_worker.run', return_value=json.dumps(
                        {**self.planned, 'chunkCount': count})) as run, \
                    self.assertRaisesRegex(RuntimeError, 'invalid bounded schedule'):
                capture_checks(self.request, self.root / 'export-request.json')
            self.assertEqual(run.call_count, 1)

    def test_valid_ineligible_plans_keep_the_existing_capture_route(self):
        """Single-frame and missing-forward legacy cases still receive full replay."""
        for reason in ('single-frame-session', 'forward-evidence-unavailable'):
            planned = {'status': 'native-qc-phases-ineligible', 'reason': reason}
            with self.subTest(reason=reason), \
                    mock.patch('studio.native_short_worker.run', return_value=json.dumps(planned)) as run, \
                    mock.patch('studio.native_short_worker.verify_files') as verify:
                capture_checks(self.request, self.root / 'export-request.json')
            self.assertEqual(run.call_count, 2)
            self.assertEqual(verify.call_count, 2)
            self.assertTrue(run.call_args.args[0][1].endswith('/native_short_capture.mjs'))
            self.assertEqual(len(run.call_args.args[0]), 3)

    def test_malformed_forward_authority_never_falls_back(self):
        """Planner failures and unknown ineligibility reasons remain hard failures."""
        with mock.patch('studio.native_short_worker.run', side_effect=RuntimeError('forward evidence changed')) as run, \
                self.assertRaisesRegex(RuntimeError, 'forward evidence changed'):
            capture_checks(self.request, self.root / 'export-request.json')
        self.assertEqual(run.call_count, 1)
        result = {'status': 'native-qc-phases-ineligible', 'reason': 'malformed-receipt'}
        with mock.patch('studio.native_short_worker.run', return_value=json.dumps(result)) as run, \
                self.assertRaisesRegex(RuntimeError, 'invalid legacy reason'):
            capture_checks(self.request, self.root / 'export-request.json')
        self.assertEqual(run.call_count, 1)

    def test_schedule_tampering_stops_before_the_next_chunk(self):
        """A completed child does not authorize changed later work."""
        def child(command):
            result = self.phase_child(command)
            if command[3] == 'chunk':
                self.schedule.write_text('substituted schedule')
            return result
        with mock.patch('studio.native_short_worker.run', side_effect=child) as run, \
                self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            capture_checks(self.request, self.root / 'export-request.json')
        self.assertEqual(run.call_count, 2)

    def test_receipt_changed_during_finish_is_rejected(self):
        """The finisher cannot replace a digest the parent observed after an earlier child."""
        def child(command):
            result = self.phase_child(command)
            if command[3] == 'finish':
                (self.schedule.parent / 'chunk-000/receipt.json').write_text('edited receipt')
            return result
        with mock.patch('studio.native_short_worker.run', side_effect=child), \
                self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            capture_checks(self.request, self.root / 'export-request.json')

    def test_compiler_result_changed_during_finish_is_rejected(self):
        """Compiled preparation remains bound after the last child reports success."""
        def child(command):
            result = self.phase_child(command)
            if command[3] == 'finish':
                self.compiler_receipt.write_text('substituted compiler result')
            return result
        with mock.patch('studio.native_short_worker.run', side_effect=child), \
                self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            capture_checks(self.request, self.root / 'export-request.json')

    def test_compiled_html_changed_between_chunks_is_rejected(self):
        """Unchanged receipt text cannot authorize changed compiler output bytes."""
        def child(command):
            result = self.phase_child(command)
            if command[3] == 'chunk':
                (self.compiler_receipt.parent / 'compiled/index.html').write_text('changed HTML')
            return result
        with mock.patch('studio.native_short_worker.run', side_effect=child) as run, \
                self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            capture_checks(self.request, self.root / 'export-request.json')
        self.assertEqual(run.call_count, 2)

    def test_compiler_payload_changed_between_chunks_is_rejected(self):
        """Serialized configuration and compiler data stay bound to the current plan."""
        def child(command):
            result = self.phase_child(command)
            if command[3] == 'chunk':
                self.compiler_payload.write_bytes(b'substituted compiler payload')
            return result
        with mock.patch('studio.native_short_worker.run', side_effect=child) as run, \
                self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            capture_checks(self.request, self.root / 'export-request.json')
        self.assertEqual(run.call_count, 2)

    def test_malformed_compiler_inventory_cannot_launch_capture(self):
        """Missing receipts, invalid digests and external paths are not compiler authority."""
        valid = self.planned['compilerPins']
        foreign = self.root / 'unrelated.txt'
        foreign.write_text('external to compiler preparation')
        invalid = (None, {}, {str(self.compiler_receipt): digest(self.compiler_receipt)},
                   {name: sha for name, sha in valid.items() if name != str(self.compiler_payload)},
                   {**valid, str(foreign): digest(foreign)},
                   {**valid, str(self.compiler_receipt): 'not-a-digest'})
        for pins in invalid:
            with self.subTest(pins=pins), \
                    mock.patch('studio.native_short_worker.run', return_value=json.dumps(
                        {**self.planned, 'compilerPins': pins})) as run, \
                    self.assertRaises(RuntimeError):
                capture_checks(self.request, self.root / 'export-request.json')
            self.assertEqual(run.call_count, 1)

    def test_child_timeout_cannot_continue_or_publish_final_checks(self):
        """An interrupted chunk stops the phase loop; its files cannot count as passed."""
        with mock.patch('studio.native_short_worker.run', side_effect=[json.dumps(self.planned),
                        subprocess.TimeoutExpired('native-qc', 180)]) as run, \
                self.assertRaises(subprocess.TimeoutExpired):
            capture_checks(self.request, self.root / 'export-request.json')
        self.assertEqual(run.call_count, 2)
        self.assertFalse((self.root / 'native-frames.json').exists())

    def test_shared_child_deadline_remains_180_seconds(self):
        """Phased calls retain the existing bounded subprocess runner."""
        from studio.native_short_delivery import run
        with mock.patch('studio.native_short_delivery.subprocess.run') as child:
            run(['/test/node', 'bounded-qc-chunk'])
        self.assertEqual(child.call_args.kwargs['timeout'], 180)
        self.assertTrue(child.call_args.kwargs['check'])


if __name__ == '__main__':
    unittest.main()
