"""Bounded visual-reuse dispatch regressions, not decoded creator quality proof."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio.assemble_picture_reuse import _receipt, picture_reuse_input_hash
from captions.caption_operations import new_caption_track, upsert_caption_range
from captions.caption_words import stable_word_id
from current_render_graph_cli import _clean_graph_hit
from cut_preview_io import file_hash


class SourceFloatVisualReuseTests(unittest.TestCase):
    """An already-held graph cannot supply missing current external-input proof."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.base, self.final = self.root / 'base.mp4', self.root / 'final.mp4'
        self.base.write_bytes(b'TEST ONLY dispatch base, not playable media')
        self.final.write_bytes(b'TEST ONLY dispatch final, not playable media')
        self.bus = SimpleNamespace(admission=SimpleNamespace(tools={}, code=[]))
        self.plan = {'planVersion': 1, 'target': {'mode': 'longform', 'scope': 'trim'},
                     'cutTrack': [{'sourceId': 'raw-1', 'start': 0, 'end': 1}]}
        track = upsert_caption_range(new_caption_track('off'), {
            'wordIds': [stable_word_id('raw-1', 0)], 'styleId': 'karaoke',
            'mode': 'karaoke-word', 'placement': 'bottom-center'})
        self.visual_plans = [
            {**self.plan, 'graphicsTrack': [{'kind': 'statement-card', 'outStart': 0, 'outEnd': 1}]},
            {**self.plan, 'captionsTrack': track, 'captions': {'burn': True}}]

    def _job(self, plan: dict) -> SimpleNamespace:
        job = SimpleNamespace(base=str(self.base), out=str(self.final), plan=plan)
        sha = file_hash(self.final)
        pointer = {'schemaVersion': 2, 'audioClockPolicy': 'source-float-v2',
            'pictureReuseInputHash': picture_reuse_input_hash(job, self.bus), 'finalSha256': sha}
        (self.root / 'program_audio.v2.json').write_text(json.dumps(pointer))
        (self.root / 'final.mp4.assembled.json').write_text(json.dumps({'authorityHash': sha}))
        return job

    def test_unproved_template_and_caption_inputs_decline_picture_reuse(self) -> None:
        for plan in self.visual_plans:
            with self.subTest(plan=plan), patch('audio.assemble_picture_reuse._graph_authority', return_value={}):
                self.assertIsNone(_receipt(self._job(plan), self.bus))

    def test_same_caption_plan_key_does_not_prove_current_transcript_bytes(self) -> None:
        transcript = self.root / 'transcript.json'
        transcript.write_text('{"word":"before"}')
        job = self._job(self.visual_plans[1])
        before = picture_reuse_input_hash(job, self.bus)
        transcript.write_text('{"word":"corrected"}')
        self.assertEqual(before, picture_reuse_input_hash(job, self.bus))
        with patch('audio.assemble_picture_reuse._graph_authority', return_value={}):
            self.assertIsNone(_receipt(job, self.bus), 'missing dependency must decline, not bless old pixels')

    def test_whole_graph_hit_cannot_bypass_fresh_visual_composite(self) -> None:
        graph = {'toolchainHash': 'TEST ONLY held toolchain'}
        for plan in self.visual_plans:
            plan_path = self.root / 'plan.json'
            plan_path.write_text(json.dumps(plan))
            config = SimpleNamespace(phase='assemble', force_full=False, defer_active=False,
                inputs=SimpleNamespace(audio_clock_policy='source-float-v2', plan_path=plan_path))
            with self.subTest(plan=plan), patch('current_render_graph_cli.compile_graph', return_value=(graph, [])), \
                    patch('current_render_graph_cli.classify_nodes', return_value=([], ['node-final'])):
                self.assertFalse(_clean_graph_hit(config, (graph, {}), False, graph['toolchainHash']))

    def test_legacy_graph_dispatch_keeps_existing_behavior(self) -> None:
        graph = {'toolchainHash': 'TEST ONLY held toolchain'}
        config = SimpleNamespace(phase='assemble', force_full=False, defer_active=False,
            inputs=SimpleNamespace(audio_clock_policy='legacy-v1'))
        with patch('current_render_graph_cli.compile_graph', return_value=(graph, [])), \
                patch('current_render_graph_cli.classify_nodes', return_value=([], ['node-final'])):
            self.assertTrue(_clean_graph_hit(config, (graph, {}), False, graph['toolchainHash']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
