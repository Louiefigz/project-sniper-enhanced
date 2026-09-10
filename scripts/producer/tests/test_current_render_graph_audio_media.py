"""Actual synthetic opt-in source-float-v2 graph commands, never creator approval."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
PRODUCER = PROJECT / 'scripts/producer'
sys.path[:0] = [str(PRODUCER), str(PRODUCER / 'tests')]

from test_render_source_audio_media import _fixture
from test_render_audio_cache_media import with_synthetic_music
from current_render_graph_audio import validate_audio_command
from current_render_graph_store import load_active
from current_render_graph_contract import object_hash
from audio.audio_mix_picture import packet_signature
from audio.assemble_picture_reuse import _receipt
from audio.render_audio_cache import load_source_bus
from cut_preview_io import bound_json, file_hash
from types import SimpleNamespace
from _current_render_graph_audio_revision import audio_only_revision


class ActualSourceAudioGraph(unittest.TestCase):
    """Record real child commands, phase timing and independent graph/output reads."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create the retained synthetic fixture before every sequential scenario."""
        cls.root = Path(tempfile.mkdtemp(prefix='sniper-v2-graph-cli-', dir='/private/tmp'))
        cls.plan, cls.manifest = _fixture(cls.root)
        # One silent visual seam is part of the base picture from the start, so a later
        # sfx flip on that seam is an audio-only revision (a NEW seam is a picture change).
        cls.plan["transitions"] = [{"outTime": 1.0, "kind": "white-flash", "sfx": False}]
        chord = ("aevalsrc='0.04*(sin(2*PI*(220+55*floor(t/0.5))*t)"
                 "+sin(2*PI*(277.18+69.295*floor(t/0.5))*t)"
                 "+sin(2*PI*(329.63+82.4075*floor(t/0.5))*t))':s=48000:d=3")
        cls.manifest = with_synthetic_music(cls.root, cls.manifest, chord)
        cls.output = cls.root / 'producer'
        cls.output.mkdir()
        (cls.root / 'project.json').write_text(json.dumps({'resolvedIntent': cls.plan['target']}))
        (cls.output / 'edit_plan.json').write_text(json.dumps(cls.plan))
        (cls.root / 'source_plan.json').write_text(json.dumps(cls.plan))
        cls.base = cls.output / 'base.mp4'
        cls.timings = {}
        cls.base_rows = cls.command('base', 'base')
        os.replace(cls.output / 'final.mp4', cls.base)
        cls.rows = cls.command('assemble', 'assemble')
        cls.initial = load_active(cls.output)
        cls.initial_pointer = bound_json(cls.output / 'program_audio.v2.json')
        print('retained synthetic graph fixture:', cls.root, flush=True)

    @classmethod
    def command(cls, phase: str, label: str, extra: tuple[str, ...] = (), check: bool = True) -> list[dict] | tuple[int, list[dict], str]:
        """Run the original real CLI and retain its exact command output."""
        plan, manifest = cls.output / 'edit_plan.json', Path(cls.manifest['_path'])
        out = cls.output / 'final.mp4'
        if phase == 'base':
            plan = cls.root / 'source_plan.json'
            child = [str(PRODUCER / 'render.py'), str(plan), str(manifest), str(cls.output),
                     '--skip-graphics', '--workdir', str(cls.output / 'work')]
        else:
            child = [str(PRODUCER / 'assemble.py'), str(cls.base), str(plan), str(out),
                     '--fingerprint', str(cls.output / 'base.fingerprint.json'), '--manifest', str(manifest)]
        child += ['--audio-clock-policy', 'source-float-v2', '--require-source-set-admission']
        args = [str(PROJECT / '.venv/bin/python'), str(PRODUCER / 'current_render_graph_cli.py'),
            '--phase', phase, '--producer-dir', str(cls.output), '--plan', str(plan),
            '--manifest', str(manifest), '--base', str(cls.base), '--output', str(out),
            '--audio-clock-policy', 'source-float-v2',
            '--next-plan', str(cls.output / 'edit_plan.json'), *extra, '--', *child]
        started = time.monotonic()
        result = subprocess.run(args, capture_output=True, text=True, timeout=180,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(PRODUCER)})
        cls.timings[label] = time.monotonic() - started
        (cls.root / f'{label}.stdout.log').write_text(result.stdout)
        (cls.root / f'{label}.stderr.log').write_text(result.stderr)
        (cls.root / 'commands-timing.json').write_text(json.dumps(cls.timings, indent=2))
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        if not check:
            return result.returncode, rows, result.stderr
        if result.returncode:
            raise RuntimeError(f'{label} failed:{result.returncode}; retained{cls.root}; {result.stderr[-2000:]}')
        return rows

    def test_01_real_base_handoff_and_raw_master_graph(self) -> None:
        """Check the actual base handoff and retained master graph."""
        self.assertTrue(any(row.get('status') == 'render_graph_base_handoff' for row in self.base_rows))
        self.assertTrue(any(row.get('status') == 'render_graph_committed' for row in self.rows))
        nodes = {row['nodeId']: row for row in self.initial[0]['nodes']}
        self.assertEqual(nodes['node-dialogue']['kind'], 'dialogue-stem')
        self.assertIn('node-dialogue', nodes['node-composite']['dependencies'])
        self.assertIn('audio.programReceipt', nodes['node-final']['inputDigests'])
        self.assertFalse((self.output / '.render-graph-v1/PENDING_BASE.json').exists())

    def test_02_real_noop_has_no_child_render(self) -> None:
        """Require the unchanged graph to avoid a child command."""
        rows = self.command('assemble', 'noop')
        self.assertTrue(any(row.get('status') == 'render_graph_cache_hit' for row in rows))
        self.assertFalse(any(row.get('status') == 'done' for row in rows))
        self.assertEqual(object_hash(load_active(self.output)[0]), object_hash(self.initial[0]))

    def test_03_music_revision_retains_picture_and_raw_dialogue_node(self) -> None:
        """Check a real music revision preserves picture and raw dialogue."""
        picture = packet_signature(str(self.output / 'final.mp4'), 'v:0')
        changed = copy.deepcopy(self.plan)
        changed['music'] = {'enabled': True, 'assetId': 'test-only-bed', 'gapDb': 12}
        (self.output / 'edit_plan.json').write_text(json.dumps(changed))
        rows = self.command('assemble', 'music-revision')
        done = next(row for row in rows if row.get('status') == 'done')
        self.assertTrue(done['pictureReusedForAudioRevision'])
        self.assertTrue(done['delivery']['qualified'])
        self.assertEqual(picture, packet_signature(str(self.output / 'final.mp4'), 'v:0'))
        latest = load_active(self.output)
        self.assertIn('node-dialogue', latest[1]['reusedNodeIds'])
        self.assertIn('node-final', latest[1]['dirtyNodeIds'])

    def test_03b_finishing_revision_reuses_picture_and_raw_bus_and_rebuilds_the_master(self) -> None:
        """Check cleanup and gain reuse the admitted picture and raw dialogue bus.

        The full-program master is rebuilt. Source, timeline, base and dialogue
        stay reused; composite and final are dirty because they share final.mp4.
        """
        picture = packet_signature(str(self.output / 'final.mp4'), 'v:0')
        before = bound_json(self.output / 'program_audio.v2.json')
        before_receipt = bound_json(Path(before['programMasterReceiptPath']))
        plan = bound_json(self.output / 'edit_plan.json')
        plan.update({'audioEnhance': {'preset': 'voice'},
                     'audioGain': [{'outStart': 1.0, 'outEnd': 1.5, 'dB': 6}]})
        (self.output / 'edit_plan.json').write_text(json.dumps(plan))
        rows = self.command('assemble', 'finishing-revision')
        done = next(row for row in rows if row.get('status') == 'done')
        self.assertTrue(done['pictureReusedForAudioRevision'])
        self.assertFalse(done['programMasterReused'])
        self.assertTrue(done['delivery']['qualified'])
        self.assertEqual(picture, packet_signature(str(self.output / 'final.mp4'), 'v:0'))
        rebuilt = next(row for row in rows if row.get('status') == 'program_master_rebuilt')
        self.assertIn('finishing settings changed', rebuilt['reason'])
        after = bound_json(self.output / 'program_audio.v2.json')
        self.assertNotEqual(before['audioProgramInputHash'], after['audioProgramInputHash'])
        receipt = bound_json(Path(after['programMasterReceiptPath']))
        self.assertEqual(receipt['sourceBusReceiptHash'], before_receipt['sourceBusReceiptHash'],
                         'the original admitted raw dialogue bus is reused, not re-rendered')
        self.assertEqual(receipt['finishing']['settings']['audioGain'][0]['dB'], 6.0)
        self.assertGreater(receipt['finishing']['cleanup']['measuredLatencySamples'], 0)
        latest = load_active(self.output)
        self.assertEqual(latest[1]['dirtyNodeIds'], ['node-composite', 'node-final'], latest[1]['dirtyNodeIds'])
        for node_id in ('node-source', 'node-timeline', 'node-base', 'node-dialogue'):
            self.assertIn(node_id, latest[1]['reusedNodeIds'])
        self.assertFalse(any(row.get('stage') == 'graphics' for row in rows))
        self.assertEqual(next(row for row in latest[0]['nodes'] if row['nodeId'] == 'node-final')
                         ['inputDigests']['audio.programReceipt'], after['programMasterReceiptHash'])

    def _audio_only_revision(self, label: str, change: dict) -> tuple[list[dict], dict]:
        """Delegate the unchanged real-command revision and artifact assertions."""
        return audio_only_revision(self, label, change)

    def test_03e_gain_only_revision_reuses_every_picture_node(self) -> None:
        """Check gain-only revision records its new finishing value."""
        _rows, after = self._audio_only_revision('gain-only-revision', {'audioGain': [{'outStart': 1.0, 'outEnd': 1.5, 'dB': 3}]})
        receipt = bound_json(Path(after['programMasterReceiptPath']))
        self.assertEqual(receipt['finishing']['settings']['audioGain'][0]['dB'], 3.0)

    def test_03f_cleanup_change_reuses_every_picture_node(self) -> None:
        """Check cleanup revision records the requested preset."""
        _rows, after = self._audio_only_revision('cleanup-revision', {'audioEnhance': {'preset': 'voice-strong'}})
        receipt = bound_json(Path(after['programMasterReceiptPath']))
        self.assertEqual(receipt['finishing']['cleanup']['preset'], 'voice-strong')

    def test_03g_music_gap_and_existing_seam_sfx_change_reuse_every_picture_node(self) -> None:
        """Check the existing seam gains its precisely timed SFX cue."""
        plan = bound_json(self.output / 'edit_plan.json')
        music = {**plan['music'], 'gapDb': 14}
        _rows, after = self._audio_only_revision('music-sfx-revision', {'music': music,
            'transitions': [{'outTime': 1.0, 'kind': 'white-flash', 'sfx': True}]})
        receipt = bound_json(Path(after['programMasterReceiptPath']))
        self.assertEqual(receipt['music']['settings']['gapDb'], 14)
        self.assertEqual(receipt['finishing']['sfx']['cues'][0]['startSample'], 33_600)

    def test_03c_deferred_reassembly_reuses_the_held_finished_master(self) -> None:
        """Unchanged audio inputs + a held ACTIVE graph: a deferred-active re-run executes the
        real assemble child, which reuses the held finished master (no remaster) and holds the
        graph files through publication; the candidate is staged, ACTIVE stays put."""
        before = bound_json(self.output / 'program_audio.v2.json')
        active = load_active(self.output)
        picture = packet_signature(str(self.output / 'final.mp4'), 'v:0')
        rows = self.command('assemble', 'deferred-reuse', extra=('--defer-active',))
        done = next(row for row in rows if row.get('status') == 'done')
        self.assertTrue(done['programMasterReused'])
        self.assertTrue(done['delivery']['qualified'])
        reused = next(row for row in rows if row.get('status') == 'program_master_reused')
        self.assertEqual(reused['receiptHash'], before['programMasterReceiptHash'])
        self.assertTrue(any(row.get('status') == 'render_graph_candidate_staged' for row in rows))
        after = bound_json(self.output / 'program_audio.v2.json')
        self.assertEqual(after['programMasterReceiptHash'], before['programMasterReceiptHash'])
        self.assertEqual(after['audioProgramInputHash'], before['audioProgramInputHash'])
        self.assertEqual(picture, packet_signature(str(self.output / 'final.mp4'), 'v:0'))
        self.assertEqual(load_active(self.output), active)

    def test_03d_changed_pointer_or_foreign_master_never_publishes(self) -> None:
        """Reject foreign master/hash changes while leaving final and pointer intact.
        test_program_master_reuse separately covers the helper's rebuild branch.
        """
        pointer_path = self.output / 'program_audio.v2.json'
        current_bytes = pointer_path.read_bytes()
        current = json.loads(current_bytes)
        final_before = file_hash(self.output / 'final.mp4')
        foreign_path = Path(self.initial_pointer['programMasterReceiptPath'])   # the first (plain) master
        foreign = bound_json(foreign_path)
        self.assertNotEqual(foreign['receiptHash'], current['programMasterReceiptHash'])
        cases = (('foreign-valid-master', {'programMasterReceiptPath': str(foreign_path),
                                           'programMasterReceiptHash': foreign['receiptHash'],
                                           'audioProgramInputHash': foreign['audioProgramInputHash']}),
                 ('resealed-hash', {'programMasterReceiptHash': 'f' * 64}))
        try:
            for label, mutation in cases:
                pointer_path.write_text(json.dumps({**current, **mutation}))
                self._assert_tampered_master(label, (pointer_path, current, mutation, final_before))
        finally:
            pointer_path.write_bytes(current_bytes)
        self.assertEqual(json.loads(pointer_path.read_text()), current)

    def _assert_tampered_master(self, label: str, context: tuple) -> None:
        """Keep one rejected pointer case inside its original named subtest."""
        pointer_path, current, mutation, final_before = context
        with self.subTest(label=label):
            code, rows, stderr = self.command('assemble', f'tampered-{label}', check=False)
            self.assertNotEqual(code, 0)
            self.assertFalse(any(row.get('status') == 'done' for row in rows))
            self.assertFalse(any(row.get('status') == 'program_master_reused' for row in rows))
            self.assertIn('held prior render graph', stderr + ''.join(json.dumps(row) for row in rows))
            self.assertEqual(file_hash(self.output / 'final.mp4'), final_before)
            self.assertEqual(json.loads(pointer_path.read_text()), {**current, **mutation})

    def test_04_mismatched_policy_rejects_before_any_cache_hit(self) -> None:
        """Reject mismatched policies and caller-supplied graph-owned hashes."""
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            validate_audio_command('source-float-v2', ('assemble.py',))
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            validate_audio_command('legacy-v1', ('assemble.py', '--audio-clock-policy', 'source-float-v2'))
        validate_audio_command('source-float-v2', ('assemble.py', '--audio-clock-policy=source-float-v2'))
        for supplied in (('--source-bus-receipt-hash', '0' * 64),
                         ('--source-bus-receipt-hash=' + '0' * 64,)):
            with self.subTest(supplied=supplied), self.assertRaisesRegex(RuntimeError, 'owned by the graph'):
                validate_audio_command('source-float-v2',
                    ('assemble.py', '--audio-clock-policy=source-float-v2', *supplied))

    def _reuse_inputs(self) -> tuple:
        """Open actual retained authority without mocking its source or cache proof."""
        plan = bound_json(self.output / 'edit_plan.json')
        graph = load_active(self.output)[0]
        dialogue = next(row for row in graph['nodes'] if row['nodeId'] == 'node-dialogue')
        bus = load_source_bus(plan, self.manifest, (str(self.output), str(self.base)),
                              dialogue['inputDigests']['audio.sourceReceipt'])
        return SimpleNamespace(base=str(self.base), out=str(self.output / 'final.mp4'), plan=plan), bus

    def test_05_resealed_substituted_picture_cannot_claim_old_graph_lineage(self) -> None:
        """A valid changed picture and self-consistent sidecars are not prior authority."""
        job, bus = self._reuse_inputs()
        names = ('final.mp4', 'final.mp4.assembled.json', 'program_audio.v2.json')
        before = {name: (self.output / name).read_bytes() for name in names}
        alternate = self.root / 'TEST-ONLY-negated-picture.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', job.out,
            '-vf', 'negate', '-c:v', 'libx264', '-c:a', 'copy', str(alternate)], check=True, timeout=20)
        try:
            (self.output / 'final.mp4').write_bytes(alternate.read_bytes())
            changed = file_hash(self.output / 'final.mp4')
            sidecar = json.loads(before[names[1]])
            sidecar['authorityHash'] = changed
            (self.output / names[1]).write_text(json.dumps(sidecar))
            pointer = json.loads(before[names[2]])
            pointer['finalSha256'] = changed
            (self.output / names[2]).write_text(json.dumps(pointer))
            with self.assertRaisesRegex(RuntimeError, 'held prior render graph'):
                _receipt(job, bus)
        finally:
            for name, raw in before.items():
                (self.output / name).write_bytes(raw)

    def test_06_no_graph_means_recomposite_not_sidecar_authority(self) -> None:
        """Ungrapped direct CLI output is valid media but cannot authorize reuse."""
        job, bus = self._reuse_inputs()
        active = self.output / '.render-graph-v1/ACTIVE.json'
        hidden = active.with_suffix('.TEST-ONLY.json')
        os.replace(active, hidden)
        try:
            self.assertIsNone(_receipt(job, bus))
        finally:
            os.replace(hidden, active)


if __name__ == '__main__':
    unittest.main(verbosity=2)
