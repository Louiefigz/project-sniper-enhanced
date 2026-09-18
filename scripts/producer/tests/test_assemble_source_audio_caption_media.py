"""Actual 1080p synthetic caption/music final; never speech or perceptual approval."""
from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import assemble
import render as renderer
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from captions.caption_operations import new_caption_track, upsert_caption_range
from captions.caption_words import stable_word_id
from cut_delivery_authority import seal_render_delivery, verify_delivered_cuts
from cut_preview_io import bound_json, file_hash
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _context, _fixture


def _inputs(root: Path) -> tuple[dict, dict, dict]:
    """Keep NTSC/J-cut/right-only/silent timing, adding explicitly synthetic words."""
    plan, manifest = _fixture(root, '1920x1080')
    words = [{'word': 'SYNTHETIC', 'start': .1, 'end': .4},
             {'word': 'FIXTURE', 'start': .45, 'end': .8},
             {'word': 'END', 'start': 3.65, 'end': 3.8}]
    transcript = root / 'source/synthetic.transcript.json'
    transcript.write_text(json.dumps({'transcript': [{'words': words}]}))
    manifest['sources'][0]['transcriptPath'] = str(transcript)
    chord = ("aevalsrc='0.04*(sin(2*PI*(220+55*floor(t/0.5))*t)"
             "+sin(2*PI*(277.18+69.295*floor(t/0.5))*t)"
             "+sin(2*PI*(329.63+82.4075*floor(t/0.5))*t))':s=48000:d=3")
    manifest = with_synthetic_music(root, manifest, chord)
    track = new_caption_track('off')
    for indexes in ((0, 1), (2,)):
        track = upsert_caption_range(track, {
            'wordIds': [stable_word_id('raw-1', index) for index in indexes],
            'styleId': 'karaoke', 'mode': 'karaoke-word', 'placement': 'bottom-center'})
    # Explicit track is present in the base plan but burn is deferred to assemble.
    plan = {**plan, 'captionsTrack': track, 'captions': {'burn': False}}
    final = {**copy.deepcopy(plan), 'captions': {'burn': True},
             'music': {'enabled': True, 'assetId': 'test-only-bed', 'gapDb': 12}}
    return plan, manifest, final


def _frame(path: Path, index: int) -> np.ndarray:
    """Decode a selected frame for a visible-caption support check, not still-only QC."""
    video = cv2.VideoCapture(str(path))
    try:
        video.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = video.read()
        if not ok:
            raise RuntimeError(f'synthetic frame {index} did not decode: {path}')
        return frame
    finally:
        video.release()


class CaptionSourceAudioMediaTests(unittest.TestCase):
    """Full actual output QC plus independent frame/sample/receipt readbacks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix='sniper-f1-caption-final-', dir='/private/tmp'))
        base_plan, cls.manifest, cls.plan = _inputs(cls.root)
        cls.ctx = _context(cls.root, base_plan, cls.manifest, SOURCE_FLOAT_POLICY_V2)
        cls.ctx.skip_graphics = True
        cls.output = Path(cls.ctx.out_dir)
        print('retained synthetic caption/audio fixture:', cls.root, flush=True)
        with (cls.root / 'base.log').open('w') as log, contextlib.redirect_stdout(log):
            renderer.render(cls.ctx, audit=True)
        cls.base = cls.output / 'base.mp4'
        os.replace(cls.output / 'final.mp4', cls.base)
        seal_render_delivery(str(cls.output), str(cls.base), base_plan, True)
        Path(cls.ctx.plan_path).write_text(json.dumps(cls.plan))
        cls.job = assemble.AssembleJob(str(cls.base), cls.plan, str(cls.output / 'final.mp4'), None,
            fingerprint_path=str(cls.output / 'base.fingerprint.json'), manifest=cls.manifest['_path'],
            audio_clock_policy=SOURCE_FLOAT_POLICY_V2, plan_path=cls.ctx.plan_path,
            source_bus_receipt_hash=cls.ctx.source_audio_bus.receipt['receiptHash'])
        with (cls.root / 'assemble.log').open('w') as log, contextlib.redirect_stdout(log), \
                patch('assemble._assemble_captioned', wraps=assemble._assemble_captioned) as compositor:
            cls.result = assemble.assemble(cls.job)
            compositor.assert_called_once()

    def test_encoded_caption_music_final_passes_complete_qc_and_exact_audio_clock(self) -> None:
        self.assertTrue(self.result['captions']['burned'])
        self.assertEqual(self.result['captions']['cues'], 2)
        self.assertTrue(self.result['delivery']['qualified'])
        self.assertFalse(self.result.get('pictureReusedForAudioRevision', False))
        audit = bound_json(self.output / 'audit_report.json')
        self.assertNotEqual(audit['overall'], 'fail')
        self.assertEqual(audit['finalSha256'], file_hash(Path(self.job.out)))
        self.assertTrue(any(row['name'] == 'caption_authority' and row['status'] == 'pass'
                            for row in audit['checks']))
        pointer = bound_json(self.output / 'program_audio.v2.json')
        master = bound_json(Path(pointer['programMasterReceiptPath']))
        self.assertEqual(master['totalSamples'], 192192)
        self.assertEqual(master['masteredAudio']['codec'], 'pcm_f32le')
        self.assertTrue(master['wholeProgramMeasurement']['audioDecodeSucceeded'])
        self.assertEqual(master['detectorReference']['appliedTo'], 'sidechain-only')
        verify_delivered_cuts(str(self.output), self.job.out, self.plan)

    def test_early_and_late_captions_are_visible_in_decoded_final(self) -> None:
        differences = {}
        for index in (0, 7, 100, 111):
            before, after = _frame(self.base, index), _frame(Path(self.job.out), index)
            self.assertEqual(after.shape, (1080, 1920, 3))
            error = np.max(np.abs(before.astype(np.int16) - after.astype(np.int16)), axis=2)
            differences[index] = int(np.count_nonzero(error > 40))
        (self.root / 'caption-pixel-check.json').write_text(json.dumps(differences))
        self.assertGreater(differences[7], differences[0] + 300)
        self.assertGreater(differences[111], differences[100] + 300)

    def test_early_and_late_decoded_caption_boxes_follow_landscape_position(self) -> None:
        """Catch the prior middle-of-frame portrait-safe-box clamp in actual pixels."""
        boxes = {}
        for index in (7, 111):
            before, after = _frame(self.base, index), _frame(Path(self.job.out), index)
            delta = np.max(np.abs(before.astype(np.int16) - after.astype(np.int16)), axis=2)
            selected = (delta > 40) & (after[:, :, 1] > 150) & (after[:, :, 2] > 180)
            selected[:, :480] = False
            selected[:, 1440:] = False
            rows = np.flatnonzero(np.count_nonzero(selected, axis=1) > 15)
            self.assertGreater(len(rows), 15)
            top, bottom = int(rows[0]), int(rows[-1])
            boxes[index] = {'top': top, 'bottom': bottom, 'declaredBaseline': round(1080 * .7)}
            self.assertGreater(top, 1080 * .64, 'bottom-center must not land in mid-frame')
            self.assertLessEqual(bottom, round(1080 * .7))
            self.assertLess(round(1080 * .7) - bottom, 30)
        (self.root / 'caption-decoded-boxes.json').write_text(json.dumps(boxes))


if __name__ == '__main__':
    unittest.main(verbosity=2)
