"""Selected-source clocks, packet preservation and failure boundaries without encoding."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import file_hash
from edit.selected_sources_contract import selection_request, source_sections
from edit.selected_sources_media import media_info, packet_origin
from studio.native_selected_sources import dialogue_inputs


class SelectedSourcesTests(unittest.TestCase):
    """Exercise public validation against real file identities and exact rational clocks."""

    def setUp(self) -> None:
        """Use a tiny inert original; media commands are never invoked by these unit tests."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'inert TEST source identity')
        sha = file_hash(self.source)
        self.file = f'assets/{sha}.mp4'
        self.request = {'schemaVersion': 1, 'handleSeconds': 1,
                        'sources': [{'file': self.file, 'path': str(self.source), 'sha256': sha}],
                        'ranges': [{'sourceFile': self.file, 'start': 20, 'end': 25}]}

    def test_out_of_order_and_repeated_views_share_one_bounded_section(self) -> None:
        """Merge nearby handles while retaining source order independently of editorial order."""
        self.request['ranges'] += [{'sourceFile': self.file, 'start': 10, 'end': 12},
                                  {'sourceFile': self.file, 'start': 24, 'end': 28},
                                  {'sourceFile': self.file, 'start': 20, 'end': 25}]
        selected = selection_request(self.request)
        actual = source_sections(selected, {self.file: Fraction(100)})
        self.assertEqual([(row['start'], row['end']) for row in actual], [('9', '13'), ('19', '29')])
        self.assertEqual(selected['ranges'], self.request['ranges'])

    def test_handles_clip_to_source_and_align_audio_start(self) -> None:
        """A fractional boundary remains rational and cannot extend beyond the recording."""
        self.request['ranges'] = [{'sourceFile': self.file, 'start': 1.1234567, 'end': 3.8}]
        actual = source_sections(selection_request(self.request), {self.file: Fraction(4)})[0]
        self.assertEqual(Fraction(actual['start']) * 48000, 5925)
        self.assertEqual(actual['end'], '4')

    def test_changed_original_is_rejected(self) -> None:
        """No prior range selection authorizes changed source bytes."""
        self.source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            selection_request(self.request)

    def test_unsupported_audio_clock_or_channels_require_explicit_adaptation(self) -> None:
        """Never silently introduce a new resampling phase or surround downmix."""
        import json
        video = {'codec_type': 'video', 'codec_name': 'h264', 'start_time': '0', 'duration': '100'}
        audio = {'codec_type': 'audio', 'sample_rate': '48000', 'channels': 2, 'start_time': '0'}
        for changed in ({'sample_rate': '44100'}, {'channels': 6}, {'start_time': '0.1'}):
            value = {'streams': [video, {**audio, **changed}], 'format': {'duration': '100'}}
            with patch('edit.selected_sources_media.command', return_value=json.dumps(value)), \
                    self.subTest(changed=changed), self.assertRaisesRegex(ValueError, '48 kHz'):
                media_info(self.source, {'ffprobe': '/TEST/ffprobe'})

    def test_invalid_and_out_of_source_ranges_fail(self) -> None:
        """Reject nonfinite, reversed, foreign and unbounded intervals."""
        for value in (float('nan'), float('inf'), -1, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.request['ranges'][0]['start'] = value
                selection_request(self.request)
        self.request['ranges'][0]['start'] = 26
        with self.assertRaises(ValueError):
            selection_request(self.request)
        self.request['ranges'][0]['start'] = 20
        with self.assertRaisesRegex(ValueError, 'exceeds source'):
            source_sections(selection_request(self.request), {self.file: Fraction(24)})
        self.request['ranges'][0]['sourceFile'] = 'assets/foreign.mp4'
        with self.assertRaisesRegex(ValueError, 'unknown source'):
            selection_request(self.request)

    def test_missing_fields_and_excessive_handles_fail(self) -> None:
        """Requests cannot smuggle encoder options or silently default a range policy."""
        self.request['encoder'] = 'lossy'
        with self.assertRaises(ValueError):
            selection_request(self.request)
        del self.request['encoder']
        self.request['handleSeconds'] = 6
        with self.assertRaises(ValueError):
            selection_request(self.request)

    def packets(self, shift: Fraction = Fraction(0)) -> list[dict]:
        """Use reordered presentation timestamps to catch incorrect B-frame clock shifts."""
        return [{'data_hash': f'hash-{index}', 'ptsTime': Fraction(pts, 30) + shift,
                 'dtsTime': Fraction(index - 2, 30) + shift, 'durationTime': Fraction(1, 30),
                 'flags': 'K_' if index == 0 else '__'} for index, pts in enumerate((0, 3, 1, 2))]

    def test_packets_keep_reordering_with_one_exact_translation(self) -> None:
        """Only a uniform source-to-local translation preserves the decoding contract."""
        self.assertEqual(packet_origin(self.packets(Fraction(1001, 30)), self.packets()), Fraction(1001, 30))

    def test_changed_packet_or_timing_is_rejected(self) -> None:
        """Same codec/container does not prove unchanged compressed picture or timing."""
        for field, changed in [('data_hash', 'different'), ('ptsTime', Fraction(8)),
                               ('dtsTime', Fraction(9)), ('durationTime', Fraction(1, 25))]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                selected = self.packets()
                selected[2][field] = changed
                packet_origin(self.packets(Fraction(10)), selected)

    def test_non_keyframe_start_is_rejected(self) -> None:
        """A matching packet slice still needs a decodable beginning."""
        selected = self.packets()
        selected[0]['flags'] = '__'
        with self.assertRaisesRegex(ValueError, 'keyframe'):
            packet_origin(self.packets(), selected)

    def test_missing_prepared_sidecar_does_not_fall_back_to_original(self) -> None:
        """Once a plan selects prepared media, absent completion cannot load the full file."""
        import json
        canvas = {'sourceFile': self.file, 'cuts': [{'start': 20, 'end': 25}]}
        (self.root / 'SHORT-PROJECT.json').write_text(json.dumps({'canvas': canvas,
            'preparedSources': {'path': '/missing/selected-sources-stage.json', 'sha256': 'a' * 64}}))
        with self.assertRaises((OSError, RuntimeError)):
            dialogue_inputs(self.root, canvas)


if __name__ == '__main__':
    unittest.main()
