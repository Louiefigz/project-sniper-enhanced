"""Qualification harness end to end with TEST stand-in exports in a TEST pool namespace.

The stand-in (tests/fixtures/pool_qualification_export.py) runs real NativeRun owners
and real ffmpeg encodes; only the exporter command is replaced. Records are written to
a temporary folder for a TEST fixture host and TEST engine identity and are never
production authority.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_pool_policy as policy
import native_work_qualification as qualification
import native_work_workload as workloads
from studio import pool_qualification as harness
from studio import pool_qualification_runner as runner
from _native_pool_fixture import TEST_ENGINE, TEST_HOST, isolate_pool, project_dir

STAND_IN = Path(__file__).resolve().parent / 'fixtures/pool_qualification_export.py'


class PoolQualificationHarnessTests(unittest.TestCase):
    """Serial references, a concurrent session, comparison and the record decision."""

    def setUp(self) -> None:
        """TEST namespace, TEST host, empty TEST record folder, stand-in exporter."""
        self.root = isolate_pool(self)
        temporary = tempfile.TemporaryDirectory(prefix='pool-qualification-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.records = self.base / 'records' / 'native-pool'
        self.records.parent.mkdir(mode=0o700)
        self.engine = mock.patch.object(workloads, 'engine_record', return_value=dict(TEST_ENGINE))
        for patch in (mock.patch.object(policy, 'host_identity', return_value=dict(TEST_HOST)),
                      mock.patch.object(qualification, 'record_directory', return_value=self.records),
                      mock.patch.object(workloads, 'current_engine', return_value=TEST_ENGINE['identity']),
                      mock.patch.object(runner, 'export_command', side_effect=self.command),
                      mock.patch('builtins.print'), self.engine):
            patch.start()
            self.addCleanup(patch.stop)
        self.project = str(project_dir(self))
        (Path(self.project) / 'SHORT-PROJECT.json').write_text(json.dumps(
            {'scope': 'TEST plan', 'canvas': {'totalFrames': 60, 'frameRate': '30/1'}}))

    def test_show_names_the_mode_a_short_render_gets(self) -> None:
        """(M-031) `show` reports the mode a Short render of not yet known length gets, from an empty TEST record."""
        with mock.patch('builtins.print') as printed:
            self.assertEqual(harness.command_show(argparse.Namespace()), 0)
        shown = json.loads(printed.call_args.args[0])
        self.assertEqual((shown['engine'], shown['shortRenderForecast']['name']), (TEST_ENGINE['identity'], 'exclusive'))

    def command(self, job: runner.Job) -> list[str]:
        """Point the stand-in at this test's namespace and record folder."""
        return [sys.executable, '-B', str(STAND_IN), job.project, job.attempt, '--test-root', str(self.root),
                '--test-record', str(self.records), *job.args]

    def jobs(self, name: str, rows: list[dict]) -> Path:
        """Write a jobs file whose attempts live in a fresh folder."""
        folder = self.base / name
        folder.mkdir()
        jobs = [{'id': row['id'], 'project': self.project, 'attempt': str(folder / row['id']),
                 'args': row.get('args', []), **({'reference': row['reference']} if 'reference' in row else {})}
                for row in rows]
        path = self.base / f'{name}.json'
        path.write_text(json.dumps({'schemaVersion': 1, 'jobs': jobs}))
        return path

    def serial(self, args: list[str] | None = None, second: list[str] | None = None) -> dict:
        """Produce serial references A and B (B may take its own arguments) and return their attempts."""
        path = self.jobs('serial', [{'id': 'A', 'args': args or []}, {'id': 'B', 'args': second or args or []}])
        options = argparse.Namespace(jobs=path, evidence=self.base / 'serial-evidence', deadline_seconds=120)
        self.assertEqual(harness.command_serial(options), 0)
        return {'A': str(self.base / 'serial/A'), 'B': str(self.base / 'serial/B')}

    def run_batch(self, rows: list[dict], record: bool = True, class_mix: str = 'heavy-only') -> tuple[int, Path]:
        """Run a concurrent qualification of two heavy slots and one audio slot."""
        path = self.jobs('concurrent', rows)
        evidence = self.base / 'concurrent-evidence'
        options = argparse.Namespace(jobs=path, evidence=evidence, deadline_seconds=120, heavy_slots=2,
                                     audio_slots=1, record=record, class_mix=class_mix)
        return harness.command_run(options), evidence

    def short(self, stage: str, lane: str = 'heavy', seconds: float = 2.0) -> dict:
        """A Short owner workload on the TEST engine."""
        return {'format': 'short', 'stage': stage, 'class': lane, 'durationSeconds': seconds,
                'pixels': 1080 * 1920, 'cache': 'unobserved', 'engine': TEST_ENGINE['identity']}

    def test_passing_concurrent_batch_writes_a_versioned_profile(self) -> None:
        """Two overlapping exports matching their references become one engine-bound Short profile."""
        references = self.serial()
        code, evidence = self.run_batch([{'id': job, 'reference': references[job]} for job in ('A', 'B')])
        self.assertEqual(code, 0)
        summary = json.loads((evidence / 'summary.json').read_text())
        self.assertEqual((summary['peakConcurrentJobs'], summary['allJobsPassed']), (2, True))
        for row in summary['jobs']:
            self.assertEqual(row['reusedWork'], [])
            self.assertTrue(all(pair['decodedEqual'] for pair in row['comparison']['media']))
            self.assertEqual({owner['mode'] for owner in row['owners']}, {'qualification-session'})
            self.assertEqual((row['cacheState'], row['format'], row['durationSeconds']), ('cold', 'short', 2.0))
        record = json.loads((self.records / qualification.RECORD_V2_NAME).read_text())
        profile = record['profiles'][0]
        self.assertEqual((profile['engine'], profile['evidence']['evidenceDirectory']), (TEST_ENGINE, str(evidence)))
        self.assertEqual(profile['workload'], {'classMix': 'heavy-only', 'formats': {'short': {
            'stages': ['pipeline'], 'maxDurationSeconds': 2.0, 'maxPixels': 1080 * 1920, 'cacheStates': ['cold']}}})
        for name in ('cpu', 'memory', 'disk', 'throughput', 'failures', 'cleanup'):
            self.assertIn(name, profile['evidence'])
        self.assertEqual(profile['evidence']['cleanup']['unverifiedOwners'], 0)
        mode = qualification.committed_mode(dict(TEST_HOST), self.short('pipeline'))
        self.assertEqual((mode.name, mode.slots, mode.record['profile']), ('qualified', {'heavy': 2, 'audio': 1},
                                                                            profile['id']))
        for other in (dict(self.short('pipeline'), format='long'), self.short('pipeline', 'audio'),
                      self.short('pipeline', seconds=2.5), self.short('capture')):
            self.assertEqual(qualification.committed_mode(dict(TEST_HOST), other).name, 'exclusive')
        self.assertTrue(json.loads((evidence / 'record-result.json').read_text())['written'])

    def test_prepared_audio_cannot_claim_mixed_and_engine_is_frozen(self) -> None:
        """Prepared audio refuses a mixed claim; an engine changed mid-batch refuses the record."""
        references = self.serial(['--prepared-audio'])
        other = dict(TEST_ENGINE, identity='f' * 64)
        with mock.patch.object(workloads, 'engine_record', side_effect=[dict(TEST_ENGINE), other]):
            code, evidence = self.run_batch([{'id': job, 'reference': references[job], 'args': ['--prepared-audio']}
                                             for job in ('A', 'B')], class_mix='mixed')
        self.assertEqual(code, 1)
        result = json.loads((evidence / 'record-result.json').read_text())
        self.assertFalse(result['written'])
        self.assertIn('the engine changed during the qualification batch', result['refusals'])
        self.assertTrue(any('only heavy owners or prepared audio' in reason for reason in result['refusals']))
        self.assertFalse((self.records / qualification.RECORD_V2_NAME).exists())

    def test_own_audio_stage_overlapping_heavy_work_qualifies_a_mixed_profile(self) -> None:
        """A job's own audio-stage owner beside another job's render backs a mixed claim."""
        own, held = ['--own-audio', '--audio-hold', '6'], ['--hold', '12']
        references = self.serial(own, held)
        code, evidence = self.run_batch([{'id': 'A', 'reference': references['A'], 'args': own},
                                         {'id': 'B', 'reference': references['B'], 'args': held}], class_mix='mixed')
        self.assertEqual(code, 0, (evidence / 'record-result.json').read_text())
        profile = json.loads((self.records / qualification.RECORD_V2_NAME).read_text())['profiles'][0]
        self.assertEqual((profile['workload']['classMix'], profile['workload']['formats']['short']['stages']),
                         ('mixed', ['audio-stage', 'pipeline']))
        self.assertGreaterEqual(profile['evidence']['overlap']['audioWithHeavyPeak'], 1)
        mode = qualification.committed_mode(dict(TEST_HOST), self.short('audio-stage', 'audio'))
        self.assertEqual((mode.name, mode.record['profile']), ('qualified', profile['id']))

    def test_decoded_difference_or_preview_evidence_is_refused(self) -> None:
        """A changed unpinned tone fails the decoded comparison; previews never qualify."""
        references = self.serial()
        code, evidence = self.run_batch([{'id': 'A', 'reference': references['A']},
                                         {'id': 'B', 'reference': references['B'], 'args': ['--tone', '660']}])
        self.assertEqual(code, 1)
        summary = json.loads((evidence / 'summary.json').read_text())
        failed = {row['id']: row['problems'] for row in summary['jobs'] if not row['passed']}
        self.assertEqual(list(failed), ['B'])
        self.assertTrue(any('decoded media differs' in problem for problem in failed['B']))
        result = json.loads((evidence / 'record-result.json').read_text())
        self.assertEqual(result['written'], False)
        self.assertFalse((self.records / qualification.RECORD_V2_NAME).exists())
        refusals = harness.record_refusals(dict(summary, allJobsPassed=True, fullExports=False), {'heavy': 2})
        self.assertIn('only complete final exports can qualify the pool', refusals)

    def test_busy_pool_refuses_a_session_before_any_export(self) -> None:
        """Qualification never shares the host with unrelated native work."""
        reference = self.base / 'TEST-reference'
        reference.mkdir()
        (reference / 'delivery.json').write_text('{"status": "TEST"}')
        lease = work.NativeWorkLease.acquire('heavy', self.project)
        self.addCleanup(lease.close)
        with self.assertRaisesRegex(RuntimeError, 'idle pool'):
            self.run_batch([{'id': 'A', 'reference': str(reference)}])
        self.assertFalse((self.base / 'concurrent-evidence').exists())
        lease.complete()

    def test_deadline_terminates_with_sigterm_and_reports_expiry(self) -> None:
        """A batch past its bound is stopped by SIGTERM; owners run their owned cleanup."""
        jobs = runner.load_jobs(self.jobs('slow', [{'id': 'S', 'args': ['--hold', '60']}]), need_reference=False)
        evidence = self.base / 'slow-evidence'
        evidence.mkdir()
        with mock.patch.object(runner, 'GRACE_SECONDS', 30):
            started = time.monotonic()
            rows, expired = runner.execute(jobs, evidence, time.monotonic() + 6, concurrent=True)
        self.assertTrue(expired)
        self.assertLess(time.monotonic() - started, 40)
        self.assertNotEqual(rows[0]['exitCode'], 0)
        owner = json.loads((Path(rows[0]['attempt']) / 'pipeline.render.json').read_text())
        self.assertIn('SIGTERM', owner['abortReason'])
        self.assertTrue(owner['cleanup']['verified'])

    def test_job_files_are_validated_exactly(self) -> None:
        """Missing references, reused attempt paths, plan-less projects and unknown keys are refused."""
        cases = [[{'id': 'A'}], [{'id': 'A', 'reference': self.project}] * 2]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                runner.load_jobs(self.jobs(f'invalid-{cases.index(rows)}', rows), need_reference=True)
        reference = self.base / 'TEST-reference'
        reference.mkdir()
        (reference / 'delivery.json').write_text('{"status": "TEST"}')
        (Path(self.project) / 'SHORT-PROJECT.json').unlink()
        with self.assertRaisesRegex(ValueError, 'SHORT-PROJECT.json or LONG-PROJECT.json'):
            runner.load_jobs(self.jobs('planless', [{'id': 'A', 'reference': str(reference)}]), need_reference=True)
        path = self.base / 'unknown.json'
        path.write_text(json.dumps({'schemaVersion': 1, 'jobs': [{'id': 'A', 'project': self.project,
                                                                  'attempt': str(self.base / 'x'), 'env': {}}]}))
        with self.assertRaisesRegex(ValueError, 'take id, project'):
            runner.load_jobs(path, need_reference=False)


class ReuseClassificationTests(unittest.TestCase):
    """Production finals share their reviewed preview and audio stage; donors disqualify."""

    def attempt(self, request: dict, stages: list[str]) -> Path:
        """A TEST attempt folder with only the request and delivery receipts."""
        temporary = tempfile.TemporaryDirectory(prefix='pool-reuse-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        (root / 'export-request.json').write_text(json.dumps({'recoverySelection': {'mode': 'fresh'}, **request}))
        (root / 'delivery.json').write_text(json.dumps({'stages': [{'phase': phase} for phase in stages]}))
        return root

    def test_reviewed_preview_and_imported_audio_are_shared_bindings(self) -> None:
        """previewFrom and an explicit audio stage are recorded, compared, never counted as reuse."""
        from studio import pool_qualification_compare as compare
        audio = {'mode': 'explicit', 'seal': '/TEST/P0/audio-stage/seal.json', 'sealSha256': 'a' * 64}
        final = self.attempt({'previewFrom': '/TEST/P0/motion-previews.json', 'audioStage': audio},
                             ['audio-stage-reused'])
        self.assertEqual(compare.reused_work(final), [])
        self.assertEqual(compare.shared_bindings(final)['audioStageSeal'], audio['seal'])
        own = self.attempt({'audioStage': {'mode': 'attempt', 'seal': '/TEST/own/seal.json'}}, ['audio-stage'])
        self.assertIsNone(compare.shared_bindings(own)['audioStageSeal'])

    def test_donors_restored_stages_and_recovery_still_disqualify(self) -> None:
        """Finished media, captures, sections and resumes never qualify concurrency."""
        from studio import pool_qualification_compare as compare
        donor = self.attempt({'captureStage': '/TEST/capture-stage.json', 'previewSectionDonors': {'x': 'y'},
                              'recoverySelection': {'mode': 'automatic', 'reused': 'audio'}},
                             ['capture-reused', 'preview-picture-0-reused'])
        self.assertEqual(compare.reused_work(donor), ['captureStage', 'previewSectionDonors',
                                                      'automatic recovery: audio', 'capture-reused',
                                                      'preview-picture-0-reused'])


if __name__ == '__main__':
    unittest.main()
