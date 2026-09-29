"""Tiny generated codec fixtures; never production timing or capacity evidence."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from cut_preview_io import write_new
from native_review_calibration_media import prepare_fixture, read_fixture, validate_spec
from studio.native_segments.review_media import derive_media


class CalibrationFixtureTests(unittest.TestCase):
    """Exercise actual generated input validation and unchanged package media ops."""

    def setUp(self) -> None:
        """Keep technical codec fixtures in an isolated temporary directory."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.tools = {name: str(Path(shutil.which(name)).resolve()) for name in ('node', 'ffmpeg', 'ffprobe')}
        self.spec = {'canvas': {'width': 64, 'height': 36, 'frameRate': '25/1', 'totalFrames': 300},
                     'frameRange': [3, 263], 'pattern': 'motion'}

    def test_generated_windows_and_pcm_are_technical_only(self) -> None:
        """Two real windows and absolute master excerpts need no production seals."""
        value = prepare_fixture(self.spec, self.tools, self.root)
        self.assertEqual(len(value['windows']), 2)
        inputs = read_fixture(self.root / 'technical-inputs.json', self.tools)
        target = self.root / 'package'
        target.mkdir()
        result = derive_media(inputs, target)
        self.assertEqual(result['audio']['startSample'], 5760)
        self.assertEqual(result['audio']['endSampleExclusive'], 504960)
        self.assertTrue(result['assembly']['piecePayloadsIdentical'])
        self.assertFalse(value['productionAuthority'])
        self.assertFalse(list(self.root.rglob('*stage.json')))
        self.assertFalse((self.root / 'export-request.json').exists())

    def test_rational_short_tail_preserves_non_aac_aligned_samples(self) -> None:
        """A rational tail is not rounded to one AAC frame or to whole seconds."""
        self.spec.update(frameRange=[3, 24], pattern='texture')
        self.spec['canvas'].update(frameRate='30000/1001', totalFrames=30)
        prepare_fixture(self.spec, self.tools, self.root)
        inputs = read_fixture(self.root / 'technical-inputs.json', self.tools)
        target = self.root / 'package'
        target.mkdir()
        result = derive_media(inputs, target)
        samples = result['audio']['samples']
        self.assertNotEqual(samples % 1024, 0)
        self.assertEqual(result['media']['audioClock']['presentedSamples'], samples)

    def test_mutated_command_refuses_before_package_processing(self) -> None:
        """Strict schema and provenance checks reject ambiguity before processing."""
        self.spec['frameRange'] = [0, 3]
        value = prepare_fixture(self.spec, self.tools, self.root)
        boolean_version = copy.deepcopy(value)
        boolean_version['schemaVersion'] = True
        value['windows'][0]['encoding']['encoderContractSha256'] = '0' * 64
        variants = [(boolean_version, 'invalid technical input record'), (value, 'encoder arguments changed')]
        for index, (record, message) in enumerate(variants):
            changed = self.root / f'changed-{index}.json'
            write_new(changed, record)
            with self.assertRaisesRegex(ValueError, message):
                read_fixture(changed, self.tools)

    def test_invalid_spec_refuses_unbounded_or_ambiguous_work(self) -> None:
        """Synthetic input limits are checked before invoking any generator."""
        variants = [dict(self.spec, frameRange=[True, 3]), dict(self.spec, pattern='arbitrary-filter')]
        excessive = copy.deepcopy(self.spec)
        excessive['canvas']['totalFrames'] = 45001
        variants.append(excessive)
        for value in variants:
            with self.assertRaises(ValueError):
                validate_spec(value)
