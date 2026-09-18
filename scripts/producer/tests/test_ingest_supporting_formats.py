"""Explicit SVG ingress rejection without changing shared raster/video support."""
from __future__ import annotations

import gzip
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ingest
from _ingest_admission_fixture import probe, runner
from ingest_admission import IngressCandidate, admit_ingest_candidates, collect_ingest_candidates
from ingest_admitted_scan import catalog_admitted_broll
from ingest_probe import IMAGE_EXTS, MEDIA_EXTS, VIDEO_EXTS, probe_media


class SupportingFormatIngestTests(unittest.TestCase):
    """Recognition is distinct from admission and native format selection."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.input = self.root / 'input'
        self.input.mkdir()
        self.output = self.root / 'output'

    def test_svg_and_svgz_are_discovered_then_rejected_before_any_runner_or_probe(self) -> None:
        for filename in ('logo.svg', 'logo.SVG', 'logo.svgz', 'broll/brands/logo.svg', 'broll/logo.SVGZ'):
            with self.subTest(filename=filename):
                source = self.input / filename
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
                with patch('ingest_admission.admit_external_media') as admit, \
                        patch('ingest_probe.ffprobe_json') as ffprobe:
                    with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ.*unsupported'):
                        ingest.build_manifest(self.input, self.output, no_transcribe=True)
                    admit.assert_not_called()
                    ffprobe.assert_not_called()
                self.assertFalse((self.output / 'asset_manifest.json').exists())
                source.unlink()
        self.assertTrue({'.svg', '.svgz'}.issubset(MEDIA_EXTS))

    def test_direct_file_and_preconstructed_candidate_cannot_bypass_rejection(self) -> None:
        source = self.input / 'logo.svg'
        source.write_bytes(b'<svg><script>unsafe()</script></svg>')
        with patch('ingest_admission.admit_external_media') as admit:
            with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                ingest.build_manifest(source, self.output, no_transcribe=True)
            with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                admit_ingest_candidates([IngressCandidate(source, 'broll')], self.output)
            admit.assert_not_called()

    def test_renamed_active_relative_resource_and_compressed_documents_are_not_probed(self) -> None:
        bodies = [b'<svg><script>unsafe()</script></svg>',
                  b'<svg><image href="file:///private/file"/></svg>',
                  b'<svg><use href="//example.test/asset.svg#mark"/></svg>',
                  b'\xef\xbb\xbf<?xml version="1.0"?><svg onbegin="unsafe()"/>',
                  gzip.compress(b'<svg/>'), '<svg/>'.encode('utf-16'),
                  b' ' * 2048 + b'<svg><image href="file:///private/file"/></svg>',
                  b'\x00\x00\xfe\xff' + '<svg/>'.encode('utf-32-be')]
        for index, body in enumerate(bodies):
            source = self.input / f'pretend-{index}.png'
            source.write_bytes(body)
            with self.subTest(index=index), patch('ingest_probe.ffprobe_json') as ffprobe:
                with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                    collect_ingest_candidates([source], None, None)
                snapshot = self.input / f'snapshot-{index}.media'
                snapshot.write_bytes(body)
                with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                    probe_media(str(snapshot))
                ffprobe.assert_not_called()

    def test_supported_shared_formats_still_reach_admission_with_original_provenance(self) -> None:
        broll = self.input / 'broll'
        broll.mkdir()
        extensions = sorted(IMAGE_EXTS | VIDEO_EXTS)
        for index, extension in enumerate(extensions):
            (broll / f'asset-{index}{extension}').write_bytes(f'image TEST ONLY {index}'.encode())
        candidates = collect_ingest_candidates([], broll, None)
        self.assertEqual(len(candidates), len(extensions))
        with patch('ingest_admission.admit_external_media', side_effect=runner) as admit:
            admission = admit_ingest_candidates(candidates, self.output)
        self.assertEqual(admit.call_count, len(extensions))
        with patch('ingest_admitted_scan.probe_media', side_effect=probe), patch('ingest_admitted_scan.status'):
            rows = catalog_admitted_broll(broll, [], admission.media_by_original)
        self.assertEqual(len(rows), len(extensions))
        for row in rows:
            media = admission.media_by_original[row['originalPath']]
            self.assertEqual(row['path'], media.snapshot_path)
            self.assertEqual(row['sourceSha256'], media.sha256)
            self.assertEqual(row['admissionReceiptSha256'], media.receipt_sha256)
        self.assertTrue({'.gif', '.bmp', '.tiff'}.issubset(IMAGE_EXTS))
        self.assertTrue({'.webm', '.mkv', '.avi'}.issubset(VIDEO_EXTS))

    def test_catalog_rejects_retained_svg_kind_before_host_reprobe_or_cache_write(self) -> None:
        broll = self.input / 'broll'
        broll.mkdir()
        source = broll / 'disguised.png'
        source.write_bytes(b'image TEST ONLY')
        admission = admit_ingest_candidates(collect_ingest_candidates([], broll, None), self.output, runner)
        media = admission.media_by_original[str(source)]
        mapping = {str(source): replace(media, media_kind='svg')}
        with patch('ingest_admitted_scan.probe_media') as ffprobe:
            with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                catalog_admitted_broll(broll, [], mapping)
            ffprobe.assert_not_called()
        self.assertFalse((broll / 'broll_catalog.json').exists())

    def test_extra_broll_rows_cannot_introduce_svg_outside_folder_scan(self) -> None:
        source = self.input / 'loose.svg'
        source.write_bytes(b'<svg/>')
        with patch('ingest_admitted_scan.probe_media') as ffprobe:
            with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                catalog_admitted_broll(None, [{'path': str(source)}], {})
            ffprobe.assert_not_called()

    def test_document_prefix_guard_cannot_block_on_a_fifo(self) -> None:
        fifo = self.input / 'fake.png'
        os.mkfifo(fifo)
        with patch('ingest_probe.ffprobe_json') as ffprobe:
            with self.assertRaisesRegex(RuntimeError, 'regular file'):
                probe_media(str(fifo))
            ffprobe.assert_not_called()

    def test_mpeg_layer_one_header_collision_reaches_admission_and_probe(self) -> None:
        # FF FE: MPEG-1 Layer I with CRC. 90 C4: valid bitrate/rate/channel header fields.
        frame_prefix = b'\xff\xfe\x90\xc4' + bytes(64)
        payload = {'format': {'duration': '1'}, 'streams': [
            {'codec_type': 'audio', 'codec_name': 'mp1', 'channels': 1, 'sample_rate': '44100'}]}
        for extension in ('.mp3', '.mpg'):
            source = self.input / f'layer-one{extension}'
            source.write_bytes(frame_prefix)
            with self.subTest(extension=extension):
                candidates = collect_ingest_candidates([source], None, None)
                with patch('ingest_admission.admit_external_media', side_effect=runner) as admit:
                    admission = admit_ingest_candidates(candidates, self.output)
                    admit.assert_called_once()
                snapshot = admission.media_by_original[str(source)].snapshot_path
                with patch('ingest_probe.ffprobe_json', return_value=payload) as ffprobe:
                    result = probe_media(snapshot)
                    ffprobe.assert_called_once_with(snapshot)
                self.assertTrue(result.audio_present)
                self.assertEqual(result.audio_sample_rate, 44100)

    def test_utf16_svg_requires_document_shape_after_bom_and_still_rejects(self) -> None:
        for index, (bom, encoding) in enumerate(((b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'))):
            source = self.input / f'utf16-{index}.png'
            document = '\n  <?xml version="1.0"?><svg><image href="file:///private/file"/></svg>'
            source.write_bytes(bom + document.encode(encoding))
            with self.subTest(encoding=encoding), patch('ingest_probe.ffprobe_json') as ffprobe:
                with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                    collect_ingest_candidates([source], None, None)
                with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                    probe_media(str(source))
                ffprobe.assert_not_called()

    def test_whitespace_padded_utf16_and_utf32_documents_do_not_exhaust_prefix_guard(self) -> None:
        encodings = ((b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'),
                     (b'\xff\xfe\x00\x00', 'utf-32-le'), (b'\x00\x00\xfe\xff', 'utf-32-be'))
        for index, (bom, encoding) in enumerate(encodings):
            source = self.input / f'padded-{index}.png'
            source.write_bytes(bom + (' ' * 2048 + '<svg/>').encode(encoding))
            with self.subTest(encoding=encoding), patch('ingest_probe.ffprobe_json') as ffprobe:
                with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                    collect_ingest_candidates([source], None, None)
                with self.assertRaisesRegex(RuntimeError, 'SVG/SVGZ'):
                    probe_media(str(source))
                ffprobe.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
