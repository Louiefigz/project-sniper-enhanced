"""Native long-form preparation behavior with inert fixtures and no media execution."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.long_sources_html import inspect_html, transform
from studio.long_sources_project import MANIFEST, check_project, hash_file, project_inputs, selection, write_project
from studio.long_sources import prepare_project

HTML = '''<!doctype html><html><body>
<div id="root" data-composition-id="test" data-width="1920" data-height="1080" data-duration="6" data-fps="24">
<video id="a" src="assets/raw.mp4" muted data-start="0" data-duration="3" data-media-start="100"></video>
<video id="b" src='assets/raw.mp4' muted data-start="3" data-duration="3" data-media-start="300"></video>
<audio id="master" src="assets/master.wav" data-start="0" data-duration="6" data-volume="0.9"></audio>
<p id="caption">Unchanged words &amp; punctuation.</p>
</div><script>window.__timelines={}; /* unchanged motion */</script></body></html>'''


class LongSourcesTests(unittest.TestCase):
    """Only source URLs/offsets change; original files and the working pipeline stay intact."""

    def setUp(self) -> None:
        """Create real files with clearly inert TEST media, never call codecs."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.original = self.root / 'original'
        (self.original / 'assets').mkdir(parents=True)
        (self.original / 'index.html').write_text(HTML)
        (self.original / 'assets/raw.mp4').write_bytes(b'TEST original picture')
        (self.original / 'assets/master.wav').write_bytes(b'TEST unchanged program narration')
        self.inputs = project_inputs(self.original)
        source = self.inputs['bindings']['assets/raw.mp4']
        sections = [self.section(source['file'], start) for start in (99, 299)]
        self.result = {'selection': {'sources': [source]}, 'sections': sections}
        self.binding = {'path': str(self.root / 'TEST-stage.json'), 'sha256': 'a' * 64}
        self.enterContext(patch('studio.long_sources_project.read_package', return_value=(self.result, {})))

    def section(self, source: str, start: int) -> dict:
        """Prepared section metadata uses a real immutable test file hash."""
        file = self.root / f'prepared-{start}.mp4'
        file.write_bytes(f'TEST selected {start}'.encode())
        sha = hash_file(file)
        return {'sourceFile': source, 'video': {'file': f'assets/{sha}.mp4', 'path': str(file),
            'sha256': sha, 'bytes': file.stat().st_size, 'sourceStart': str(start),
            'sourceEnd': str(start + 5), 'sourceOrigin': str(start)}, 'audio': None}

    def test_selection_retains_original_order_offsets_and_canvas(self) -> None:
        """Keep source-time selections independent of output timeline positions."""
        actual = selection(self.inputs)
        self.assertEqual([(row['start'], row['end']) for row in actual['ranges']], [(100, 103), (300, 303)])
        self.assertEqual(len(actual['sources']), 1)
        self.assertEqual(self.inputs['preservedProgramAudio'][0]['id'], 'master')

    def test_writer_reader_preserve_master_graphics_and_all_original_bytes(self) -> None:
        """Replace only picture paths and offsets while copying the master exactly."""
        destination = self.root / 'prepared'
        before = copy.deepcopy(self.inputs)
        record = write_project(self.inputs, self.binding, destination)
        self.assertEqual(check_project(destination), record)
        self.assertEqual(project_inputs(self.original), before)
        self.assertFalse((destination / 'assets/raw.mp4').exists())
        self.assertEqual((destination / 'assets/master.wav').read_bytes(), (self.original / 'assets/master.wav').read_bytes())
        expected = HTML.replace('assets/raw.mp4', record['mappings'][0]['preparedFile'], 1)
        expected = expected.replace('assets/raw.mp4', record['mappings'][1]['preparedFile'], 1)
        expected = expected.replace('data-media-start="100"', 'data-media-start="1"').replace('data-media-start="300"', 'data-media-start="1"')
        self.assertEqual((destination / 'index.html').read_text(), expected)

    def test_title_revision_can_reuse_the_same_sealed_sections(self) -> None:
        """A visual-only revision must retain its existing media mappings."""
        changed = HTML.replace('Unchanged words', 'A revised title')
        before = transform(HTML, self.inputs['bindings'], self.result)
        after = transform(changed, self.inputs['bindings'], self.result)
        self.assertEqual(before[1], after[1])
        self.assertNotEqual(before[0], after[0])

    def test_writer_preserves_windows_newlines_outside_source_attributes(self) -> None:
        """Writing prepared HTML must not normalize unrelated authored bytes."""
        original = HTML.replace('\n', '\r\n').encode()
        (self.original / 'index.html').write_bytes(original)
        destination = self.root / 'prepared'
        record = write_project(project_inputs(self.original), self.binding, destination)
        result = (destination / 'index.html').read_bytes()
        self.assertEqual(result.count(b'\r\n'), original.count(b'\r\n'))
        self.assertEqual(check_project(destination), record)

    def test_rehashed_output_cannot_change_a_prepared_offset(self) -> None:
        """Reject executable changes even when an output manifest is rehashed."""
        destination = self.root / 'prepared'
        record = write_project(self.inputs, self.binding, destination)
        html = (destination / 'index.html').read_text().replace('data-media-start="1"', 'data-media-start="0"', 1)
        (destination / 'index.html').write_text(html)
        record['files']['index.html'] = hash_file(destination / 'index.html')
        (destination / MANIFEST).write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            check_project(destination)

    def test_missing_or_changed_media_and_source_fail(self) -> None:
        """Cold reads must detect altered output media and original inputs."""
        destination = self.root / 'prepared'
        write_project(self.inputs, self.binding, destination)
        (destination / 'assets/master.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'file changed'):
            check_project(destination)
        (self.original / 'index.html').write_text(HTML.replace('100', '101'))
        with self.assertRaisesRegex(ValueError, 'original long-form project changed'):
            check_project(destination)

    def test_unsupported_timing_and_missing_coverage_do_not_fall_back(self) -> None:
        """Unproven clocks and uncovered passages must fail explicitly."""
        for change in ('data-playback-rate="2" ', 'data-playback-start="1" '):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'speed-one'):
                inspect_html(HTML.replace('<video ', '<video ' + change, 1))
        with self.assertRaisesRegex(ValueError, 'literal'):
            inspect_html(HTML.replace('data-start="3"', 'data-start="a + 0"'))
        self.result['sections'].pop()
        with self.assertRaisesRegex(ValueError, 'does not cover'):
            transform(HTML, self.inputs['bindings'], self.result)

    def test_dynamic_reference_and_nested_media_require_explicit_adaptation(self) -> None:
        """Reject references that cannot be safely mapped on the root timeline."""
        (self.original / 'index.html').write_text(HTML.replace('/* unchanged motion */', 'const source="assets/raw.mp4";'))
        with self.assertRaisesRegex(ValueError, 'additional reference'):
            project_inputs(self.original)
        (self.original / 'index.html').write_text(HTML)
        (self.original / 'nested.html').write_text(HTML)
        with self.assertRaisesRegex(ValueError, 'root timeline'):
            project_inputs(self.original)

    def test_existing_pipeline_project_cannot_be_overwritten(self) -> None:
        """Require a separate destination before touching an original project."""
        with self.assertRaisesRegex(ValueError, 'new destination'):
            prepare_project(self.original, self.original)
        with self.assertRaisesRegex(ValueError, 'new destination'):
            prepare_project(self.original, self.original / 'child')
        self.assertEqual(project_inputs(self.original), self.inputs)

    def test_standalone_ranged_audio_is_rejected_without_altering_master(self) -> None:
        """Preserve the program master instead of guessing a separate audio edit."""
        (self.original / 'index.html').write_text(HTML.replace('id="master"', 'id="master" data-media-start="10"'))
        with self.assertRaisesRegex(ValueError, 'complete-program WAV'):
            project_inputs(self.original)
        self.assertEqual((self.original / 'assets/master.wav').read_bytes(), b'TEST unchanged program narration')

    def test_unquoted_existing_offset_cannot_create_duplicate_attributes(self) -> None:
        """Reject an ambiguous replacement rather than adding a second offset."""
        changed = HTML.replace('data-media-start="100"', 'data-media-start=100')
        with self.assertRaisesRegex(ValueError, 'quoted data-media-start'):
            transform(changed, self.inputs['bindings'], self.result)

    def test_failed_original_preflight_never_prepares_or_changes_media(self) -> None:
        """A failed original validation must stop before media preparation."""
        with patch('studio.long_sources.preflight', return_value={'status': 'blocked'}), \
                patch('studio.long_sources.prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'original long-form static checks failed'):
                prepare_project(self.original, self.root / 'prepared')
        prepare.assert_not_called()
        self.assertFalse((self.root / 'prepared').exists())
        self.assertEqual(project_inputs(self.original), self.inputs)


if __name__ == '__main__':
    unittest.main()
