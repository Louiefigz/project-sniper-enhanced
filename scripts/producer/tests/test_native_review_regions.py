"""A longer timeline's three copy revisions invalidate only declared scene neighborhoods."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from studio.native_review_regions import region_packet, preview_windows


class NativeReviewRegionsTests(unittest.TestCase):
    """Real file inventories; no synthetic hashes claim media or editorial approval."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve()
        (self.project / 'compositions').mkdir()
        canvas = {'frameRate': '30/1', 'totalFrames': 9000, 'width': 320, 'height': 180}
        (self.project / 'LONG-PROJECT.json').write_text(json.dumps({'canvas': canvas}))
        rows, mounts = [], []
        for index in range(10):
            relative = f'compositions/card-{index}.html'
            (self.project / relative).write_text('<html><style>p{color:red}</style><body><p>Before</p></body></html>')
            rows.append({'id': f'card-{index}', 'file': relative, 'startFrame': index * 900, 'endFrame': index * 900 + 90})
            mounts.append(f'<div data-composition-src="{relative}" data-start="{index * 30}" data-duration="3"></div>')
        (self.project / 'index.html').write_text('<html><body>' + ''.join(mounts) + '</body></html>')
        (self.project / 'REVIEW-REGIONS.json').write_text(json.dumps({'schemaVersion': 1, 'units': rows}))
        self.request = {'project': str(self.project), 'adapter': 'native-long', 'runtime': str(self.project / 'runtime'),
                        'pins': {}, 'tools': {}, 'captureMode': 'sdk-streaming', 'audioProfile': 'test'}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_three_changes_in_five_minutes_only_preview_three_complete_regions(self) -> None:
        before = region_packet(self.request)
        for index in (2, 5, 8):
            file = self.project / f'compositions/card-{index}.html'
            file.write_text(file.read_text().replace('Before', 'After'))
        after = region_packet(self.request)
        windows = preview_windows(after, before)
        self.assertEqual([row['startFrame'] for row in windows], [1740, 4380, 7140])
        self.assertEqual([row['endFrame'] for row in windows], [1950, 4650, 7350])
        self.assertEqual(sum(row['endFrame'] - row['startFrame'] for row in windows), 690)
        self.assertEqual(sum(a['hash'] == b['hash'] for a, b in zip(before['units'], after['units'])), 9)
        self.assertEqual(preview_windows(after, after), [])

    def test_instance_values_are_local_but_variable_schema_and_runtime_are_global(self) -> None:
        file = self.project / 'compositions/card-5.html'
        template = '<html data-composition-variables=\'{"variables"}\'><body><p>Before</p></body></html>'
        def write(default: object, kind: str = 'string') -> None:
            variables = json.dumps([{'id': 'title', 'type': kind, 'default': default}])
            file.write_text(template.replace('{"variables"}', variables))
        write('Before')
        before = region_packet(self.request)
        write('After')
        after = region_packet(self.request)
        self.assertEqual(len(preview_windows(after, before)), 1)
        write(2, 'number')
        self.assertGreater(len(preview_windows(region_packet(self.request), after)), 1)
        self.request['sourceCacheMode'] = 'new-mode'
        self.assertGreater(len(preview_windows(region_packet(self.request), after)), 1)

    def test_styles_code_layout_audio_and_unknown_inputs_broaden_coverage(self) -> None:
        before = region_packet(self.request)
        file = self.project / 'compositions/card-5.html'
        for source in ('<html><style>p{color:blue}</style><body><p>Before</p></body></html>',
                       '<html><script>window.changed=true</script><body><p>Before</p></body></html>',
                       '<html><body><p class="changed">Before</p></body></html>'):
            file.write_text(source)
            self.assertGreaterEqual(len(preview_windows(region_packet(self.request), before)), 10)
        (self.project / 'new-audio.wav').write_bytes(b'TEST new audio identity, not valid media')
        self.assertGreaterEqual(len(preview_windows(region_packet(self.request), before)), 10)

    def test_false_or_nested_region_mounts_are_rejected(self) -> None:
        file = self.project / 'REVIEW-REGIONS.json'
        value = json.loads(file.read_text())
        value['units'][0]['endFrame'] = 60
        file.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'actual complete'):
            region_packet(self.request)

    def test_neighbor_visible_only_in_preview_context_invalidates_its_review(self) -> None:
        mapping = self.project / 'REVIEW-REGIONS.json'
        value = json.loads(mapping.read_text())
        value['units'][1].update(startFrame=120, endFrame=210)
        mapping.write_text(json.dumps(value))
        index = self.project / 'index.html'
        index.write_text(index.read_text().replace('data-start="30"', 'data-start="4"'))
        before = region_packet(self.request)
        file = self.project / 'compositions/card-1.html'
        file.write_text(file.read_text().replace('Before', 'After'))
        after = region_packet(self.request)
        changed = {a['id'] for a, b in zip(before['units'], after['units']) if a['hash'] != b['hash']}
        self.assertEqual(changed, {'card-0', 'card-1', 'project-context-0'})

    def test_void_and_self_closing_tags_do_not_hide_timed_ancestor(self) -> None:
        index = self.project / 'index.html'
        text = index.read_text().replace('<body>', '<body><section data-start="5"><video><track/></video>')
        index.write_text(text.replace('</body>', '</section></body>'))
        with self.assertRaisesRegex(ValueError, 'root-clock'):
            region_packet(self.request)

    def test_request_and_source_decisions_are_global_without_subject_hash_cycle(self) -> None:
        file = self.project / 'VISUAL-SOURCES.json'
        receipt = {'subjectSha256': 'a' * 64, 'request': {'sha256': 'b' * 64},
                   'decisions': [{'route': 'catalog', 'reason': 'TEST initial selection'}]}
        file.write_text(json.dumps(receipt))
        before = region_packet(self.request)
        receipt['subjectSha256'] = 'c' * 64
        file.write_text(json.dumps(receipt))
        self.assertEqual(region_packet(self.request), before)
        receipt['request']['sha256'] = 'd' * 64
        file.write_text(json.dumps(receipt))
        self.assertGreaterEqual(len(preview_windows(region_packet(self.request), before)), 10)

    def test_no_dependency_map_uses_bounded_broad_samples(self) -> None:
        (self.project / 'REVIEW-REGIONS.json').unlink()
        packet = region_packet(self.request)
        windows = preview_windows(packet)
        self.assertEqual(len(windows), 3)
        self.assertTrue(all((row['endFrame'] - row['startFrame']) <= 360 for row in windows))


if __name__ == '__main__':
    unittest.main()
