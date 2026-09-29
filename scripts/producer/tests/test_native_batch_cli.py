"""native_batch.py end to end in real subprocesses with an isolated home directory."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from _budget_fixture import (
    DIRECTOR, FINGERPRINT, SOURCE, approval, b3_stand_in, handoff_confirmation, make_project, source_sha, test_mp4,
)
from _dispatch_fixture import approval_file, approval_row, launcher, media_request, tasks_file

PRODUCER = Path(__file__).resolve().parents[1]
CLI = PRODUCER / 'native_batch.py'
# The authority root comes from the account database, so HOME cannot redirect it. Each fresh
# process patches the root and the pool namespace explicitly (a child never loads the test
# base's isolation, and the forecast would read the host pool record); nothing else survives.
LAUNCHER = ('import sys, runpy; from pathlib import Path; sys.path.insert(0, sys.argv[1])\n'
            'from studio import native_budget_store as store\n'
            'root = Path(sys.argv[2]); store.default_root = lambda: root\n'
            'import native_work_lease; native_work_lease.state_root = lambda: root.parent / "native-work"\n'
            'import studio.native_budget_binding as binding; binding.default_root = store.default_root\n'
            'import studio.native_budget_forecast as forecast; forecast.heavy_lane_capacity = lambda *seconds: 1\n'
            'import native_batch\n'
            'sys.argv = [str(Path(sys.argv[1]) / "native_batch.py"), *sys.argv[3:]]\n'
            'native_batch.main()\n')


class NativeBatchCliTests(unittest.TestCase):
    """Every call is a fresh process: nothing survives except the durable authority."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        os.chmod(self.home, 0o700)
        self.root = self.home / 'budgets'
        self.env = {'PATH': os.environ['PATH'], 'PYTHONDONTWRITEBYTECODE': '1'}
        self.source = self.home / 'recording.mov'
        self.source.write_bytes(SOURCE)

    def run_cli(self, *args: str, expect: int = 0) -> dict:
        result = subprocess.run([sys.executable, '-c', LAUNCHER, str(PRODUCER), str(self.root), *args],
                                capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def approved(self, clips: str) -> list[str]:
        """Every clip's TEST approval, handed over with start."""
        return [f'--approval={clip}={approval_file(self.home, clip, approval(clip))}' for clip in clips.split(',')]

    def reserve(self, project: Path, name: str) -> subprocess.CompletedProcess:
        script = ('import sys, json; from pathlib import Path; sys.path.insert(0, sys.argv[1])\n'
                  'import studio.native_budget_binding as binding\n'
                  'binding.default_root = lambda: Path(sys.argv[4])\n'
                  'import native_work_lease\n'
                  'native_work_lease.state_root = lambda: Path(sys.argv[4]).parent / "native-work"\n'
                  'print(json.dumps(binding.reserve_launch(Path(sys.argv[2]), Path(sys.argv[3]), "final", {})))\n')
        return subprocess.run([sys.executable, '-c', script, str(PRODUCER), str(project), str(self.home / name),
                               str(self.root)], capture_output=True, text=True, env=self.env, timeout=120)

    def test_batch_lifecycle(self) -> None:
        source = ('--source', str(self.source), *self.approved('A,B'))
        optimistic = self.run_cli('start', '--batch', 'cli-batch', '--clips', 'A,B', *source, '--pool-slots', '2',
                                  expect=3)
        self.assertIn('pool qualification record admits 1 heavy job(s) at a time', optimistic['reason'])
        started = self.run_cli('start', '--batch', 'cli-batch', '--clips', 'A,B', *source, '--pool-slots', '1')
        self.assertEqual(started['status'], 'batch-started')
        self.assertTrue(started['resumed'])           # the refused start above already authorized the clock
        self.assertEqual(len(started['engine']['identity']), 64)
        self.assertIn('still active', self.run_cli('start', '--batch', 'cli-batch', '--clips', 'A', '--source',
                                                   str(self.source), *self.approved('A'), expect=3)['reason'])
        for _ in range(3):
            self.run_cli('admit', '--batch', 'cli-batch', '--clip', 'A', '--kind', 'author', '--label', 'owner')
        refused = self.run_cli('admit', '--batch', 'cli-batch', '--clip', 'A', '--kind', 'author', expect=3)
        self.assertIn('author limit reached', refused['reason'])
        self.run_cli('hold', '--batch', 'cli-batch', 'start', '--reason', 'operator priority')
        held = self.run_cli('hold', '--batch', 'cli-batch', 'end', '--reason', 'resume')
        self.assertIsNotNone(held['holds'][0]['endElapsed'])
        confirmation = handoff_confirmation(self.home / 'handoff', test_mp4(self.home))
        refused = self.run_cli('handoff', '--batch', 'cli-batch', '--clip', 'A', '--confirmation', str(confirmation),
                               expect=3)
        self.assertIn("B3's verifier refused the confirmation", refused['reason'])  # P0 adapt: B3 in src
        status = self.run_cli('status', '--batch', 'cli-batch')
        self.assertEqual(status['clips']['A']['counters']['author'], '3/3')
        self.assertEqual(status['phase'], 'preparation')
        waited = self.run_cli('wait', '--batch', 'cli-batch', '--timeout', '1')
        self.assertEqual(waited['waitResult'], 'timeout')
        self.assertEqual(waited['batch']['status'], 'active')

    def test_binding_close_gate_and_no_reset(self) -> None:
        self.run_cli('start', '--batch', 'bind-batch', '--clips', 'A', '--source', str(self.source),
                     *self.approved('A'))
        project = make_project(self.home / 'work', 'native-v1')
        revision = make_project(self.home / 'work', 'native-v2')
        self.run_cli('bind', '--batch', 'bind-batch', '--clip', 'A', str(project))
        admitted = self.reserve(project, 'attempt-1')
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        self.assertEqual(json.loads(admitted.stdout)['clipId'], 'A')
        refused = self.reserve(revision, 'attempt-2')
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('is active: bind this project', refused.stderr)
        gate = self.run_cli('close', '--batch', 'bind-batch', expect=3)
        self.assertIn('cannot be closed to reset its budgets', gate['reason'])
        status = self.run_cli('status', '--batch', 'bind-batch')
        self.assertEqual(status['clips']['A']['lastFailure']['status'], 'abandoned')
        rival = self.run_cli('start', '--batch', 'rival-batch', '--clips', 'X', '--source', str(self.source),
                             *self.approved('X'), expect=3)
        self.assertIn('bind-batch is still active', rival['reason'])
        archive = self.run_cli('archive', '--batch', 'bind-batch', '--reason', 'TEST', expect=3)
        self.assertIn('closed batch', archive['reason'])
        foreign = make_project(self.home / 'work', 'foreign', source=b'another-recording')
        self.assertEqual(self.run_cli('bind', '--batch', 'bind-batch', '--clip', 'A', str(foreign))['status'], 'bound')

    def test_status_reads_only_the_evidence_it_is_given(self) -> None:
        self.run_cli('start', '--batch', 'ev-batch', '--clips', 'A', '--source', str(self.source))
        forged = self.home / 'confirm.json'
        forged.write_text(json.dumps({'schemaVersion': 1, 'kind': 'native-visible-handoff-confirmation',
                                      'status': 'visible-handoff', 'failures': [], 'visibleHandoffAt': 'x'}))
        journal, transcript = self.home / 'stage_timings.jsonl', self.home / 'session.jsonl'
        journal.write_text('')
        transcript.write_text('')
        evidence = ('--handoff', str(forged), '--timing', str(journal), '--transcript', str(transcript))
        compact = self.run_cli('status', '--batch', 'ev-batch', *evidence)
        self.assertEqual((compact['production']['full'], compact['production']['rejectedEvidence']), (False, 1))
        self.assertEqual(compact['clips']['A']['counters']['author'], '0/3')  # the earlier fields are unchanged
        self.assertEqual(compact['clips']['A']['production']['milestones']['timestamps']['visibleHandoffAt'], None)
        production = self.run_cli('status', '--batch', 'ev-batch', '--full', *evidence)['production']
        self.assertFalse(production['evidence']['handoffs'][0]['accepted'])
        self.assertEqual(production['timingJournal']['status'], 'read')
        self.assertEqual(production['ai']['usage']['transcripts']['status'], 'linked')
        self.assertEqual(production['run']['media']['hostPool']['status'], 'no-pool-state')
        self.assertFalse((self.root.parent / 'pool-state').exists())       # status never creates pool state
        self.assertEqual(production['run']['dispatcher']['running'], False)

DELIVER = ('import sys; from pathlib import Path; sys.path[:0] = [sys.argv[1], sys.argv[1] + "/tests"]\n'
           'import _dispatch_fixture as fixture; fixture.isolate(Path(sys.argv[2]))\n'
           'from studio import native_budget_binding as binding\n'
           'grant = binding.reserve_launch(Path(sys.argv[3]), Path(sys.argv[4]), "draft", {})\n'
           'binding.record_request_outcome({"productionBudget": grant}, {"status": "native-short-review-draft",\n'
           '                               "output": sys.argv[5], "sha256": sys.argv[6]})\n')


class ApprovedStartTests(unittest.TestCase):
    """start/add-clip bind the handed-over approvals at the authorization instant; without them no task work."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        os.chmod(self.home, 0o700)
        self.root, self.testdir = self.home / 'budgets', self.home / 'test'
        self.testdir.mkdir()
        self.source = self.home / 'recording.mov'
        self.source.write_bytes(SOURCE)

    def cli(self, *args: str, expect: int = 0) -> dict:
        command = [*launcher('cli', self.root, self.testdir), args[0], '--batch', 'cli-tasks', *args[1:]]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def start(self, *approvals: str, expect: int = 0, clips: str = 'A,B') -> dict:
        return self.cli('start', '--clips', clips, *approvals, '--source', str(self.source), expect=expect)

    def record(self) -> dict:
        from studio import native_budget_store as store
        return store.read_batch(self.root, 'cli-tasks')

    def approvals(self, *clips: str) -> list[str]:
        return [f'--approval={clip}={approval_file(self.home, clip, approval(clip))}' for clip in clips]

    def test_start_binds_each_clips_title_and_script_when_the_clock_starts(self) -> None:
        started = self.start(*self.approvals('A', 'B'))
        self.assertTrue(started['approvalsBound'])
        clips = self.record()['clips']
        for clip in ('A', 'B'):
            row = clips[clip]['approvals'][0]
            self.assertEqual((row['elapsed'], row['title'], row['recordedBy']), (0.0, f'TEST title {clip}',
                                                                                 'TEST coordinator'))
            self.assertEqual(row['wordRanges'], [list(item) for item in approval(clip).word_ranges])

    def test_one_approvals_file_binds_every_clip(self) -> None:
        bundle = self.home / 'approvals.json'
        bundle.write_text(json.dumps({'schemaVersion': 1, 'kind': 'native-short-approvals',
                                      'approvals': [approval_row(clip, approval(clip)) for clip in ('A', 'B')]}))
        self.assertTrue(self.start('--approvals', str(bundle))['approvalsBound'])

    def test_incomplete_or_unverifiable_approvals_start_no_clock(self) -> None:
        self.assertIn('every declared clip', self.start(*self.approvals('A'), expect=2)['error'])
        other = self.home / 'other-transcript.json'
        other.write_text('{"transcript": []}')
        (self.home / 'wrong').mkdir()
        wrong = approval_file(self.home / 'wrong', 'B', replace(approval('B'), transcript_path=str(other)))
        refused = self.start(*self.approvals('A'), f'--approval=B={wrong}', expect=2)
        self.assertIn('not the approval\'s transcript', refused['error'])
        mixed = self.start(*self.approvals('A', 'B'), '--approvals', str(wrong), expect=2)
        self.assertIn('either as --approval', mixed['error'])
        self.assertFalse((self.root / 'batches/cli-tasks').exists())

    def test_start_and_add_clip_without_approvals_are_refused_before_anything_is_written(self) -> None:
        # Probe p6 / major 5: no approvals, no clock; exit 3 before authorization, and no notice path.
        refused = self.start(expect=3)
        self.assertIn('approved title and script', refused['reason'])
        self.assertFalse((self.root / 'batches').exists() and any((self.root / 'batches').iterdir()))
        self.start(*self.approvals('A', 'B'))
        added = self.cli('add-clip', '--clip', 'F', '--reason', 'operator added F', expect=3)
        self.assertIn('add it with --approval FILE', added['reason'])
        self.assertNotIn('F', self.record()['clips'])

    def test_ai_slots_are_declared_within_the_policy_maximum(self) -> None:
        refused = self.start(*self.approvals('A', 'B'), '--ai-slots', '17', expect=3)
        self.assertIn('the maximum is 16 concurrent AI slots, director included', refused['reason'])
        self.assertIn('native_budget_schema.AI_POLICY', refused['reason'])
        self.assertFalse((self.root / 'batches/cli-tasks').exists())
        self.assertIn('the maximum is 256', self.start(*self.approvals('A', 'B'), '--ai-slots', '6',
                                                       '--ai-reservations', '999', expect=3)['reason'])
        declared = (*self.approvals('A', 'B'), '--ai-slots', '6', '--ai-reservations', '40')
        self.start(*declared, '--pool-slots', '2', expect=3)            # authorized; setup refused, clock kept
        again = self.start(*self.approvals('A', 'B'), '--ai-slots', '8', '--pool-slots', '1', expect=3)
        self.assertIn('was authorized with 6 AI slots and 40 reservations', again['reason'])
        started = self.start(*declared, '--pool-slots', '1')
        self.assertEqual((started['resumed'], started['ai']['slots'], started['ai']['reservations'],
                          started['ai']['slotsMaximum'], started['ai']['hostQualified']), (True, 6, 40, 16, False))
        self.assertEqual(self.record()['production']['ai']['slots'], 6)

    def test_change_approval_records_the_operators_typed_change(self) -> None:
        self.start(*self.approvals('A', 'B'))
        (self.home / 'changed').mkdir()
        changed = approval_file(self.home / 'changed', 'A', approval('A', title='TEST changed title A'))
        result = self.cli('change-approval', '--clip', 'A', '--approval', str(changed), '--reason', 'operator retitled')
        self.assertEqual((result['status'], result['changed'], result['reasonRecorded']),
                         ('approval-changed', ['title'], True))  # P0 adapt: src records the reason
        rows = self.record()['clips']['A']['approvals']
        self.assertEqual((len(rows), rows[-1]['title'], rows[-1]['previous']), (2, 'TEST changed title A',
                                                                                rows[0]['identity']))
        again = self.cli('change-approval', '--clip', 'A', '--approval', str(changed), '--reason', 'x', expect=3)
        self.assertIn('already has this exact approved title and script', again['reason'])

    def test_change_approval_passes_the_reason_once_the_api_takes_one(self) -> None:
        from unittest import mock
        from studio import native_budget_store as store
        from studio.production import api, handover_commands
        self.start(*self.approvals('A', 'B'))
        seen = []

        def record_script_change(root: object, batch_id: str, clip_id: str, change: object) -> dict:
            seen.append(change.reason)                           # TEST stand-in for src's typed change (WAVES:186)
            return {'changed': ['title'], 'material': True, 'elapsed': 1.0,
                    'approval': {'title': change.approval.title, 'identity': 'i' * 64, 'previous': 'p' * 64}}
        (self.home / 'changed').mkdir()
        changed = approval_file(self.home / 'changed', 'A', approval('A', title='TEST changed title A'))
        with mock.patch.object(api, 'record_script_change', record_script_change), \
                mock.patch.object(store, 'default_root', return_value=self.root):
            result = handover_commands.cmd_change_approval(argparse.Namespace(
                batch='cli-tasks', clip='A', approval=changed, reason='operator retitled'))
        self.assertEqual((result['reasonRecorded'], seen), (True, ['operator retitled']))

    def root_cli(self, *args: str, expect: int = 0) -> dict:
        """A command that names no batch (the staged-start commands)."""
        result = subprocess.run([*launcher('cli', self.root, self.testdir), *args], capture_output=True, text=True,
                                timeout=120)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_staged_start_commands_are_refused_until_their_api_exists(self) -> None:
        listed = self.root_cli('staged-starts', expect=3)
        self.assertIn('production.api.staged_starts (unit A12), which is not in this engine', listed['reason'])
        refused = self.root_cli('discard-start', '--name', '.creating-cli-tasks-0123456789ab', '--reason',
                                'operator discards the refused start', expect=3)
        self.assertIn('production.api.discard_staged (unit A12), which is not in this engine', refused['reason'])

    def test_staged_start_commands_call_a12s_api_by_its_exact_names(self) -> None:
        from unittest import mock
        from studio import native_budget_store as store
        from studio.production import api, handover_commands
        staged = mock.Mock(return_value=[{'name': '.creating-cli-tasks-0123456789ab'}])
        discard = mock.Mock(return_value={'status': 'staged-start-discarded'})
        with mock.patch.object(api, 'staged_starts', staged, create=True), \
                mock.patch.object(api, 'discard_staged', discard, create=True), \
                mock.patch.object(store, 'default_root', return_value=self.root):
            listed = handover_commands.cmd_staged_starts(argparse.Namespace())
            handover_commands.cmd_discard_start(argparse.Namespace(name='.creating-cli-tasks-0123456789ab',
                                                                   reason='operator decision'))
        self.assertEqual(listed['staged'], [{'name': '.creating-cli-tasks-0123456789ab'}])
        staged.assert_called_once_with(self.root)
        discard.assert_called_once_with(self.root, '.creating-cli-tasks-0123456789ab', 'operator decision')

    def test_add_clip_binds_the_added_clips_approval(self) -> None:
        self.start(*self.approvals('A', 'B'))
        added = self.cli('add-clip', '--clip', 'C', '--reason', 'operator added C', '--approval',
                         str(approval_file(self.home, 'C', approval('C'))))
        self.assertEqual(added['approval']['title'], 'TEST title C')
        self.assertEqual(self.record()['clips']['C']['approvals'][0]['identity'], added['approval']['identity'])
        mismatch = self.cli('add-clip', '--clip', 'D', '--reason', 'x', '--approval',
                            str(approval_file(self.home, 'E', approval('E'))), expect=2)
        self.assertIn("approves clip 'E', not 'D'", mismatch['error'])

    def test_task_commands_claim_attach_complete_replay_and_fence(self) -> None:
        self.start(*self.approvals('A', 'B'))
        self.cli('enroll', '--task', 'director', '--handle', json.dumps(DIRECTOR), '--version', 'v1',
                 '--fingerprint', FINGERPRINT)
        self.cli('enqueue', '--tasks', str(tasks_file(self.home, 'work', [
            {'taskId': 'author-a', 'kind': 'author', 'clipId': 'A', 'version': 'v1', 'deadlineElapsed': 1400.0,
             'inputFingerprint': FINGERPRINT, 'parent': 'director'},
            {'taskId': 'lint-b', 'kind': 'check', 'clipId': 'B', 'version': 'v1', 'deadlineElapsed': 1700.0,
             'inputFingerprint': FINGERPRINT}])))
        self.assertEqual([row['taskId'] for row in self.cli('next', '--peek')['work']], ['author-a', 'lint-b'])
        claim = self.cli('next')['claim']
        self.assertEqual((claim['taskId'], claim['approval']['title']), ('author-a', 'TEST title A'))
        ref = ('--task', 'author-a', '--epoch', str(claim['epoch']), '--token', claim['token'])
        turn = {'type': 'host', 'host': 'codex', 'thread': 'TEST-thread-a', 'turn': 'TEST-turn-a'}
        self.assertTrue(self.cli('attach', *ref, '--handle', json.dumps(turn))['proceed'])
        artifact = self.home / 'plan.json'
        artifact.write_text('{"TEST": 1}')
        self.assertTrue(self.cli('complete', *ref, '--artifact', str(artifact))['committed'])
        self.assertFalse(self.cli('complete', *ref, '--artifact', str(artifact))['committed'])   # replay
        artifact.write_text('{"TEST": 2}')
        self.assertIn('different artifacts', self.cli('complete', *ref, '--artifact', str(artifact), expect=3)['reason'])
        stale = ('--task', 'author-a', '--epoch', str(claim['epoch'] + 1), '--token', claim['token'])
        self.assertIn('stale or foreign', self.cli('complete', *stale, '--artifact', str(artifact), expect=3)['reason'])
        lint = self.cli('next')['claim']
        self.cli('release', '--task', 'lint-b', '--epoch', str(lint['epoch']), '--token', lint['token'])
        self.assertEqual(self.cli('cancel-request', '--task', 'lint-b', '--reason', 'TEST not needed')['state'],
                         'cancelled')
        self.assertEqual(self.cli('reconcile')['committed'], False)

    def test_media_is_left_to_the_dispatcher_and_ai_needs_supervised_governance(self) -> None:
        self.start(*self.approvals('A', 'B'))
        director = {'type': 'process', 'pid': 7001, 'pgid': 7001, 'started': 'Sun Sep 27 10:00:00 2026'}
        self.cli('enroll', '--task', 'director', '--handle', json.dumps(director), '--version', 'v1',
                 '--fingerprint', FINGERPRINT)
        project = make_project(self.home, 'native-v1')
        request = media_request(self.home, {'batchId': 'cli-tasks', 'taskId': 'draft-a', 'clipId': 'A',
                                            'route': 'draft', 'project': str(project),
                                            'output': str(self.home / 'attempt')})
        self.cli('enqueue', '--tasks', str(tasks_file(self.home, 'work', [
            {'taskId': 'draft-a', 'kind': 'media', 'version': 'v1', 'deadlineElapsed': 1400.0,
             'mediaRequest': str(request)},
            {'taskId': 'critic-a', 'kind': 'review', 'clipId': 'A', 'version': 'v1', 'deadlineElapsed': 1500.0,
             'inputFingerprint': FINGERPRINT, 'parent': 'director'}])))
        self.assertEqual([row['taskId'] for row in self.cli('next', '--peek')['work']], ['critic-a'])
        self.assertIn('supervised governance only', self.cli('next', expect=3)['reason'])
        kept = self.root / 'dispatch/cli-tasks/requests/draft-a.json'
        self.assertEqual(kept.read_bytes(), request.read_bytes())
        self.assertEqual(oct(kept.stat().st_mode & 0o777), '0o600')

    def test_handoff_takes_visible_time_only_from_a_confirmation_b3_accepts(self) -> None:
        from unittest import mock
        from studio import native_budget_store as store
        from studio.production import commands
        self.start(*self.approvals('A', 'B'))
        project = make_project(self.home, 'native-v1')
        self.cli('bind', '--clip', 'A', str(project))
        mp4 = test_mp4(self.home / 'attempt', 'review-draft.mp4')
        delivered = subprocess.run([sys.executable, '-c', DELIVER, str(PRODUCER), str(self.root), str(project),
                                    str(self.home / 'attempt'), *mp4], capture_output=True, text=True, timeout=120)
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        views = handoff_confirmation(self.home / 'handoff', mp4, visible=False)
        refused = self.cli('handoff', '--clip', 'A', '--confirmation', str(views), expect=3)
        self.assertIn('server-verified, not a visible hand-off', refused['reason'])
        confirmation = handoff_confirmation(self.home / 'handoff', mp4)
        refused = self.cli('handoff', '--clip', 'A', '--confirmation', str(confirmation), expect=3)
        self.assertIn("B3's verifier refused the confirmation", refused['reason'])  # P0 adapt: B3 in src
        other = handoff_confirmation(self.home / 'other', test_mp4(self.home / 'other-attempt'))
        with b3_stand_in(), mock.patch.object(store, 'default_root', return_value=self.root):
            with self.assertRaisesRegex(commands.BudgetRefused, 'not a recorded delivery'):
                commands.cmd_handoff(argparse.Namespace(batch='cli-tasks', clip='A', confirmation=other))
            handed = commands.cmd_handoff(argparse.Namespace(batch='cli-tasks', clip='A', confirmation=confirmation))
        self.assertEqual(handed['handoff']['visibleHandoffAt'],
                         json.loads(confirmation.read_text())['visibleHandoffAt'])
        self.assertEqual(self.record()['clips']['A']['state'], 'handed-off')


if __name__ == '__main__':
    unittest.main()
