"""Budget admission and prepublication rejection without real media execution."""
from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio import program_master_delivery as delivery
from audio.program_delivery_signal import ProgramDeliverySignalError
from cut_preview_io import MAX_MEDIA, file_hash


class ProgramDeliveryBudgetTests(unittest.TestCase):
    """Exercise the public request while preserving the existing delivery gates."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix='sniper-delivery-budget-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.picture = self.root / 'picture.mp4'
        self.picture.write_bytes(b'PICT')
        self.output = self.root / 'output.mp4'
        self.output.write_bytes(b'PRIOR')
        self.master = SimpleNamespace(directory=str(self.root), path='master.wav',
            source_bus=SimpleNamespace(frames=24, frame_rate='24', samples=48000,
                admission=SimpleNamespace(tools={'ffmpeg': {'path': '/installed/ffmpeg'}}, policy='source-float-v2')),
            receipt={'masteringNote': None, 'receiptHash': 'a' * 64, 'audioProgramInputHash': 'b' * 64})

    def test_default_refuses_large_input_before_master_or_output_work(self) -> None:
        """A sparse fixture proves the default boundary without reading gigabytes."""
        with self.picture.open('r+b') as handle:
            handle.truncate(MAX_MEDIA + 1)
        with patch.object(delivery, 'verify_program_master') as verify, patch.object(delivery, 'render_qualified_mix') as render:
            with self.assertRaisesRegex(RuntimeError, 'over budget'):
                delivery.deliver_program_master(self.master, {}, (str(self.picture), str(self.output)))
        verify.assert_not_called()
        render.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b'PRIOR')

    def test_invalid_limits_fail_before_execution(self) -> None:
        """No accidental unlimited, fractional, or boolean budget."""
        for value in [True, False, 0, -1, 1.5, '3', None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                delivery.ProgramDeliveryRequest('picture', 'output', value)
        self.assertEqual(delivery.ProgramDeliveryRequest('picture', 'output').maximum_media_bytes, MAX_MEDIA)

    def test_explicit_limit_reaches_source_candidate_and_receipt(self) -> None:
        """The opted-in budget flows through every bounded artifact read."""
        maximum, limits = 3 * 1024 ** 3, []

        def observed_hash(path: Path, limit: int = MAX_MEDIA) -> str:
            limits.append((path.name, limit))
            return file_hash(path, limit)

        with self._media_stubs(), patch.object(delivery, 'file_hash', side_effect=observed_hash):
            result = delivery.deliver_program_master(self.master, {},
                delivery.ProgramDeliveryRequest(str(self.picture), str(self.output), maximum))
        self.assertTrue(result['published'])
        self.assertTrue(result['comparisonBindingRequired'])
        self.assertTrue(result['comparisonCandidateBound'])
        self.assertEqual(self.output.read_bytes(), b'NEWBYTES')
        self.assertEqual(limits, [('picture.mp4', maximum), ('output.mp4', maximum), ('output.mp4', maximum)])

    def test_oversized_candidate_preserves_prior_output(self) -> None:
        """AAC growth past the picture budget must fail before publication."""
        with self._media_stubs(), self.assertRaisesRegex(RuntimeError, 'delivery unqualified'):
            delivery.deliver_program_master(self.master, {},
                delivery.ProgramDeliveryRequest(str(self.picture), str(self.output), 4))
        self.assertEqual(self.output.read_bytes(), b'PRIOR')
        candidates = list(self.root.glob('.audio-mix-candidate-*/output.mp4'))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].read_bytes(), b'NEWBYTES')

    def test_failed_signal_keeps_prior_output_and_records_failure(self) -> None:
        """Local continuity failure prevents the existing atomic promotion."""
        evidence = {'passed': False, 'failedWindowCount': 1, 'failedWindowIndices': [2]}
        with self._media_stubs(), patch.object(delivery, 'verify_program_delivery_signal',
                side_effect=ProgramDeliverySignalError('dropout', evidence)):
            with self.assertRaisesRegex(RuntimeError, 'delivery unqualified'):
                delivery.deliver_program_master(self.master, {}, (str(self.picture), str(self.output)))
            retained = delivery.seal_audio_record.call_args.args[1]
        self.assertEqual(self.output.read_bytes(), b'PRIOR')
        self.assertEqual(retained['result']['localSignal'], evidence)
        self.assertFalse(retained['result']['published'])

    def test_post_comparison_mutation_cannot_become_new_baseline(self) -> None:
        """A changed candidate is rejected before another quality pass or replace."""
        def compare_then_change(master: object, candidate: str, maximum: int) -> dict:
            """Model a write after the comparison observed the original bytes."""
            sha = file_hash(Path(candidate), maximum)
            Path(candidate).write_bytes(b'CHANGED AFTER COMPARISON')
            return {'passed': True, 'candidateSha256': sha}
        with self._media_stubs(), patch.object(delivery, 'verify_program_delivery_signal',
                side_effect=compare_then_change), patch('audio.audio_mix_delivery.measure_delivery') as measure:
            with self.assertRaisesRegex(RuntimeError, 'does not bind current candidate'):
                delivery.deliver_program_master(self.master, {}, (str(self.picture), str(self.output)))
            retained = delivery.seal_audio_record.call_args.args[1]
            measure.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b'PRIOR')
        self.assertFalse(retained['result']['comparisonCandidateBound'])
        self.assertTrue(retained['result']['comparisonBindingRequired'])

    def test_unbound_legacy_renderer_keeps_existing_contract(self) -> None:
        """Callers without optional comparison identity retain the loudness gate."""
        def render(candidate: str) -> dict:
            """Write a sentinel candidate without the new optional proof field."""
            Path(candidate).write_bytes(b'COMPATIBLE')
            return {'ok': True, 'stderr': ''}
        with self._media_stubs():
            result = delivery.render_qualified_mix(str(self.output), render)
        self.assertTrue(result['published'])
        self.assertFalse(result['comparisonBindingRequired'])
        self.assertIsNone(result['comparisonCandidateBound'])
        self.assertEqual(self.output.read_bytes(), b'COMPATIBLE')

    def _media_stubs(self) -> ExitStack:
        """Replace external media work; actual budget and publication still execute."""
        stack = ExitStack()
        picture = SimpleNamespace(path=str(self.picture), time_base=Fraction(1, 24000))
        stack.enter_context(patch.object(delivery, 'verify_program_master'))
        stack.enter_context(patch.object(delivery, 'observe_picture_source', return_value=picture))
        stack.enter_context(patch.object(delivery, 'run_audio', side_effect=lambda cmd: Path(cmd[-1]).write_bytes(b'NEWBYTES')))
        stack.enter_context(patch.object(delivery, 'verify_picture_copy', return_value={'picturePacketsIdentical': True}))
        stack.enter_context(patch.object(delivery, 'aac_audio_clock', return_value={'presentedSamples': 48000}))
        stack.enter_context(patch.object(delivery, 'verify_program_delivery_signal',
            side_effect=lambda master, candidate, maximum: {'passed': True, 'failedWindowCount': 0,
                'candidateSha256': file_hash(Path(candidate), maximum)}))
        stack.enter_context(patch('audio.audio_mix_delivery.measure_delivery', return_value={'qualified': True}))
        stack.enter_context(patch.object(delivery, 'seal_audio_record', side_effect=lambda path, value: {**value, 'receiptHash': 'c' * 64}))
        return stack


if __name__ == '__main__':
    unittest.main()
