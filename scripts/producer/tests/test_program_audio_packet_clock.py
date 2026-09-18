"""Offline exact AAC continuity, priming and invocation regressions."""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from audio.program_audio_clock import aac_packet_clock, exact_aac_audio_clock


def packets() -> list[dict]:
    """Two presented frames with one explicit codec priming packet."""
    return [{'pts': -1024, 'dts': -1024, 'duration': 1024, 'side_data_list': [
        {'side_data_type': 'Skip Samples', 'skip_samples': 1024, 'discard_padding': 0}]},
        {'pts': 0, 'dts': 0, 'duration': 1024}, {'pts': 1024, 'dts': 1024, 'duration': 978}]


def document() -> dict:
    """Describe2002 samples independently of the packet list."""
    return {'streams': [{'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '48000',
        'channels': 2, 'time_base': '1/48000', 'duration_ts': 2002, 'start_pts': 0}],
        'packets': packets()}


class AACPacketClockTests(unittest.TestCase):
    """A correct duration header alone is never enough to qualify delivery."""

    def test_exact_packet_clock_passes(self) -> None:
        """Expose complete packet coverage in the delivery proof."""
        result = aac_packet_clock(packets(), 2002)
        self.assertTrue(result['allPacketsChecked'])
        self.assertEqual(result['endSampleExclusive'], 2002)
        self.assertEqual(result['leadingSkipSamples'], 1024)

    def test_no_priming_with_zero_origin_passes(self) -> None:
        """Do not require nonexistent skip metadata for zero priming."""
        self.assertEqual(aac_packet_clock(packets()[1:], 2002)['leadingSkipSamples'], 0)

    def test_one_presented_sample_is_supported(self) -> None:
        """A terminal packet can legitimately be shorter than one codec frame."""
        self.assertEqual(aac_packet_clock([{'pts': 0, 'dts': 0, 'duration': 1}], 1)['packetCount'], 1)

    def test_gap_and_overlap_fail_even_with_correct_last_end(self) -> None:
        """Reject an interior clock shift despite a matching aggregate duration."""
        for shift in (-1, 1):
            changed = packets()
            changed[1]['pts'] += shift
            changed[1]['dts'] += shift
            with self.subTest(shift=shift), self.assertRaisesRegex(RuntimeError, 'gap'):
                aac_packet_clock(changed, 2002)

    def test_nonpositive_or_oversized_duration_fails(self) -> None:
        """Invalid codec-frame durations must not compensate elsewhere."""
        for duration in (0, -1, 1025):
            changed = packets()
            changed[1]['duration'] = duration
            with self.subTest(duration=duration), self.assertRaises(RuntimeError):
                aac_packet_clock(changed, 2002)

    def test_wrong_decode_order_fails(self) -> None:
        """The owned AAC route has no legitimate frame reordering."""
        changed = packets()
        changed[1]['dts'] = -1
        with self.assertRaisesRegex(RuntimeError, 'decode-clock'):
            aac_packet_clock(changed, 2002)

    def test_missing_or_wrong_priming_fails(self) -> None:
        """Require explicit integer skip metadata matching the coded origin."""
        for skip in (None, 0, 8192, True, 1024.1):
            changed = packets()
            changed[0]['side_data_list'][0]['skip_samples'] = skip
            with self.subTest(skip=skip), self.assertRaises(RuntimeError):
                aac_packet_clock(changed, 2002)

    def test_later_skip_and_discard_are_not_accepted(self) -> None:
        """Hidden interior trims cannot inherit a zero-origin stream header."""
        for key in ('skip_samples', 'discard_padding'):
            changed = packets()
            changed[1]['side_data_list'] = [{'skip_samples': 0, 'discard_padding': 0, key: 1}]
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                aac_packet_clock(changed, 2002)

    def test_duplicate_side_metadata_fails(self) -> None:
        """Duplicated priming directives are ambiguous, even if numerically equal."""
        changed = packets()
        changed[0]['side_data_list'] *= 2
        with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
            aac_packet_clock(changed, 2002)

    def test_absent_or_malformed_packet_evidence_fails(self) -> None:
        """Missing evidence is not a successful empty packet scan."""
        for value in (None, [], {}, [None], [True]):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                aac_packet_clock(value, 2002)

    def test_wrong_endpoint_and_coerced_counts_fail(self) -> None:
        """Use the independent integer program sample count unchanged."""
        for expected in (2000, 2003, True, 2002.0, 0):
            with self.subTest(expected=expected), self.assertRaises(RuntimeError):
                aac_packet_clock(packets(), expected)

    def test_invocation_probes_actual_packets_before_decoded_count(self) -> None:
        """The real entry point must invoke the new pre-promotion packet check."""
        with patch('audio.program_audio_clock.run_audio', side_effect=[json.dumps(document()).encode(), b'1024\n1024\n']) as run:
            result = exact_aac_audio_clock('candidate.mp4', 'pinned-probe', 2002)
        self.assertIn('-show_packets', run.call_args_list[0].args[0])
        self.assertTrue(result['packetClock']['allPacketsChecked'])
        self.assertEqual(result['trailingPaddingSamples'], 46)

    def test_stream_header_does_not_hide_bad_packet_clock(self) -> None:
        """Do not continue to aggregate decoding after a malformed packet clock."""
        changed = document()
        changed['packets'][1]['pts'] += 1
        with patch('audio.program_audio_clock.run_audio', return_value=json.dumps(changed).encode()) as run:
            with self.assertRaises(RuntimeError):
                exact_aac_audio_clock('candidate.mp4', 'probe', 2002)
        self.assertEqual(run.call_count, 1)

    def test_excess_decoder_padding_fails(self) -> None:
        """One full extra frame is outside the mathematical AAC tail bound."""
        with patch('audio.program_audio_clock.run_audio', side_effect=[json.dumps(document()).encode(), b'3026\n']):
            with self.assertRaisesRegex(RuntimeError, 'padding'):
                exact_aac_audio_clock('candidate.mp4', 'probe', 2002)

    def test_timeout_cannot_fall_back_to_duration_header(self) -> None:
        """An expired owned probe remains a failure, never a metadata fallback."""
        with patch('audio.program_audio_clock.run_audio', side_effect=subprocess.TimeoutExpired('probe', 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                exact_aac_audio_clock('candidate.mp4', 'probe', 2002)

    def test_short_interior_packet_cannot_fake_contiguous_decoding(self) -> None:
        """A1024-sample decoded frame cannot use a1000-sample interior duration."""
        changed = packets()
        changed[1]['duration'] = 1000
        changed[2].update(pts=1000, dts=1000, duration=1002)
        with self.assertRaisesRegex(RuntimeError, 'interior packet'):
            aac_packet_clock(changed, 2002)


if __name__ == '__main__':
    unittest.main()
