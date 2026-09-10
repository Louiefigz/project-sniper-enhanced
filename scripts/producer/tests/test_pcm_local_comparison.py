"""Synthetic stereo PCM tests; no source media, codecs, jobs or filesystem IO."""
from __future__ import annotations

import json
import math
import unittest
from dataclasses import replace

import numpy as np

from audio.pcm_local_comparison import PCMComparisonConfig, PCMThresholds, compare_pcm


def synthetic_voice(seconds: float, sample_rate: int = 2000) -> np.ndarray:
    """Build distinct deterministic channel signals, not real recording content."""
    times = np.arange(round(seconds * sample_rate), dtype=np.float64) / sample_rate
    left = .12 * np.sin(2 * np.pi * 137 * times)
    right = .12 * np.sin(2 * np.pi * 223 * times + .37)
    return np.column_stack((left, right)).astype(np.float32)


class LocalComparisonTests(unittest.TestCase):
    """Local checks expose defects that global averages can conceal."""

    def setUp(self) -> None:
        """Create a four-second synthetic reference and an explicit padding policy."""
        self.reference = synthetic_voice(4)
        self.config = PCMComparisonConfig(len(self.reference), 2000, 0)

    def test_identical_voice_is_json_safe_and_passes(self) -> None:
        """Exact identity uses an explicit infinite-SNR flag, never JSON infinity."""
        result = compare_pcm(self.reference, self.reference.copy(), self.config)
        self.assertTrue(result['passed'])
        self.assertTrue(result['globalMetrics']['snrInfinite'])
        self.assertIsNone(result['globalMetrics']['snrDb'])
        self.assertEqual(result['failedWindowCount'], 0)
        self.assertFalse(result['humanListeningApproved'])
        self.assertFalse(result['perceptualQualityApproved'])
        json.dumps(result, allow_nan=False)

    def test_one_second_dropout_fails_despite_global_snr_above_25db(self) -> None:
        """A ten-minute average cannot conceal an interior one-second dropout."""
        reference = synthetic_voice(600, 1000)
        candidate = reference.copy()
        candidate[300000:301000] = 0
        result = compare_pcm(reference, candidate, PCMComparisonConfig(len(reference), 1000, 0))
        self.assertGreater(result['globalMetrics']['snrDb'], 25)
        self.assertAlmostEqual(result['globalMetrics']['snrDb'], 10 * math.log10(600), places=4)
        self.assertFalse(result['passed'])
        failed = [result['windows'][index] for index in result['failedWindowIndices']]
        self.assertTrue(any(row['startSample'] <= 300000 < row['endSample'] for row in failed))

    def test_one_channel_dropout_is_not_hidden_by_downmix(self) -> None:
        """Independent channel checks retain a failure even when the other plays."""
        candidate = self.reference.copy()
        candidate[2000:4000, 1] = 0
        result = compare_pcm(self.reference, candidate, self.config)
        window = next(row for row in result['windows'] if row['startSample'] == 2000)
        self.assertTrue(window['channels'][0]['passed'])
        self.assertFalse(window['channels'][1]['passed'])

    def test_small_noise_passes_conservative_engineering_bounds(self) -> None:
        """The comparison tolerates small coding-like error without fitting it away."""
        noise = np.random.default_rng(17).normal(0, .0005, self.reference.shape)
        result = compare_pcm(self.reference, self.reference + noise, self.config)
        self.assertTrue(result['passed'])
        self.assertGreater(result['globalMetrics']['snrDb'], 40)

    def test_gain_change_has_correct_ratio_correlation_and_snr(self) -> None:
        """Correlation alone must not approve a large level error."""
        result = compare_pcm(self.reference, self.reference * .5, self.config)
        measured = result['windows'][0]['channels'][0]
        self.assertAlmostEqual(measured['rmsRatio'], .5)
        self.assertAlmostEqual(measured['correlation'], 1)
        self.assertAlmostEqual(measured['snrDb'], 10 * math.log10(4))
        self.assertFalse(result['passed'])

    def test_inversion_and_lag_are_not_corrected_away(self) -> None:
        """Level matching cannot hide phase inversion or a sample offset."""
        for candidate in [-self.reference, np.roll(self.reference, 10, axis=0)]:
            with self.subTest(first_sample=candidate[0].tolist()):
                self.assertFalse(compare_pcm(self.reference, candidate, self.config)['passed'])

    def test_quiet_reference_is_distinguished_from_active_voice(self) -> None:
        """Silent identity produces no invented voice, correlation or SNR evidence."""
        silence = np.zeros_like(self.reference)
        result = compare_pcm(silence, silence, self.config)
        self.assertTrue(result['passed'])
        self.assertFalse(result['activeEvidenceAvailable'])
        self.assertEqual(result['activeChannelWindows'], 0)
        self.assertGreater(result['quietChannelWindows'], 0)
        self.assertIsNone(result['globalMetrics']['correlation'])
        self.assertIsNone(result['globalMetrics']['snrDb'])
        json.dumps(result, allow_nan=False)

    def test_quiet_section_added_noise_is_checked(self) -> None:
        """Quiet windows are not exempt from an absolute error-floor check."""
        silence = np.zeros_like(self.reference)
        result = compare_pcm(silence, np.full_like(silence, .01), self.config)
        self.assertFalse(result['passed'])
        self.assertIn('quiet-error-rms-above-bound', result['windows'][0]['channels'][0]['failures'])

    def test_nonfinite_reference_candidate_and_padding_are_rejected(self) -> None:
        """NaN cannot become zero error through a running maximum or padding trim."""
        for value in [float('nan'), float('inf'), -float('inf')]:
            with self.subTest(value=value):
                self.check_nonfinite(value)

    def check_nonfinite(self, value: float) -> None:
        """Test both compared channels and the otherwise excluded decoder tail."""
        broken = self.reference.copy()
        broken[2000, 1] = value
        self.assert_invalid(broken, self.reference, self.config)
        self.assert_invalid(self.reference, broken, self.config)
        padded = np.vstack((self.reference, np.array([[0, value]], dtype=np.float32)))
        self.assert_invalid(self.reference, padded, replace(self.config, maximum_decoder_padding=1))

    def assert_invalid(self, reference: np.ndarray, candidate: np.ndarray,
                       config: PCMComparisonConfig) -> None:
        """Require an invalid measurement to fail without emitting a pass report."""
        with self.assertRaises(ValueError):
            compare_pcm(reference, candidate, config)

    def test_stereo_and_float_input_contract_is_explicit(self) -> None:
        """Do not broadcast mono input or guess integer PCM normalization."""
        candidates = [self.reference[:, :1], self.reference[:, 0], self.reference.astype(np.int32)]
        for candidate in candidates:
            with self.subTest(shape=candidate.shape, dtype=candidate.dtype):
                self.assert_invalid(self.reference, candidate, self.config)

    def test_sample_count_and_decoder_padding_are_exact(self) -> None:
        """Permit only the explicitly declared trailing decoder padding."""
        padded = np.vstack((self.reference, np.full((3, 2), .2, dtype=np.float32)))
        config = replace(self.config, maximum_decoder_padding=3)
        result = compare_pcm(self.reference, padded, config)
        self.assertTrue(result['passed'])
        self.assertEqual(result['decodedPaddingSamples'], 3)
        self.assertEqual(result['maximumDecoderPaddingSamples'], 3)
        self.assert_invalid(self.reference, padded, self.config)
        self.assert_invalid(self.reference, self.reference[:-1], config)
        self.assert_invalid(self.reference[:-1], self.reference, config)

    def test_final_partial_hop_covers_the_entire_tail(self) -> None:
        """An off-grid program ending may not leave its last samples unchecked."""
        reference = synthetic_voice(4.3)
        candidate = reference.copy()
        candidate[-800:] = 0
        result = compare_pcm(reference, candidate, PCMComparisonConfig(len(reference), 2000, 0))
        self.assertEqual(result['windows'][-1]['endSample'], len(reference))
        self.assertEqual(result['windows'][-1]['startSample'], len(reference) - 2000)
        self.assertFalse(result['windows'][-1]['passed'])

    def test_short_clip_is_explicitly_a_short_window(self) -> None:
        """Subsecond input is fully checked rather than silently omitted."""
        reference = synthetic_voice(.25)
        result = compare_pcm(reference, reference, PCMComparisonConfig(len(reference), 2000, 0))
        self.assertEqual(len(result['windows']), 1)
        self.assertTrue(result['windows'][0]['shortWindow'])
        self.assertEqual(result['windows'][0]['endSample'], len(reference))

    def test_invalid_counts_rates_and_thresholds_are_refused(self) -> None:
        """Unknown bounds cannot silently become a permissive comparison policy."""
        for args in [(0, 48000, 0), (100, 0, 0), (100, 1001, 0), (100, 48000, -1), (100, 48000, True)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                PCMComparisonConfig(*args)
        with self.assertRaises(ValueError):
            PCMThresholds(minimum_correlation=float('nan'))
        with self.assertRaises(ValueError):
            PCMThresholds(minimum_rms_ratio=2)

    def test_finite_but_unrepresentable_energy_is_refused(self) -> None:
        """Arithmetic overflow is unavailable evidence, not perfect identity."""
        huge = np.full((100, 2), 1e300, dtype=np.float64)
        self.assert_invalid(huge, huge, PCMComparisonConfig(100, 2000, 0))


if __name__ == '__main__':
    unittest.main()
