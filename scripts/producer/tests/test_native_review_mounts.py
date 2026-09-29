"""Nested catalog mounts in review preparation: one provable root, admitted media-free mounts."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio import native_review_bundle as bundle
from studio.native_review_contract import ReviewComposition
from studio.native_review_html import adapt_html, review_mounts, without_audio
from studio.native_runtime import digest
from test_native_review_html import fixture

MOUNTS = ('<div class="clip" id="sn-title" data-composition-id="sn-title" data-composition-src="compositions/title.html" '
          'data-start="0" data-duration="0.5" data-width="1080" data-height="1920"></div>'
          '<div class="clip" id="sn-graphic" data-composition-id="sn-graphic" data-composition-src="compositions/graphic.html" '
          'data-start="0.5" data-duration="0.5" data-width="900" data-height="440"></div>')
TITLE = ('<!doctype html><html data-composition-id="sn-title"><head><meta charset="UTF-8"></head><body><template>'
         '<div id="sn-title" data-composition-id="sn-title" data-width="1080" data-height="1920" data-duration="0.5">'
         '<p>TEST title</p><svg><path d="M0 0"/></svg></div><script>/* TEST "<video>" in a string */</script>'
         '</template></body></html>')


def nested(rate: str = '25/1', total: int = 25) -> tuple[str, dict]:
    """The generated root with two catalog mounts beside the captions, as native builds emit."""
    source, canvas = fixture(rate, total)
    return source.replace('<p>Unchanged', MOUNTS + '<p>Unchanged', 1), canvas


class NestedMountHtmlTests(unittest.TestCase):
    """The HTML stage accepts only mounts provably inside the one root clock."""

    def test_nested_catalog_mounts_adapt_and_keep_every_non_audio_byte(self) -> None:
        """Nested catalog mounts adapt and keep every non-audio byte."""
        source, canvas = nested()
        adapted, proof = adapt_html(source, canvas)
        self.assertEqual([row['file'] for row in proof['mounts']], ['compositions/title.html', 'compositions/graphic.html'])
        self.assertEqual(proof['mounts'][1]['endSecondsExclusive'], '1')
        self.assertEqual(proof['audio']['removedIds'], ['spoken-source'])
        self.assertEqual(len(proof['visibility']['windows']), 1)
        restored = adapted
        for row in proof['visibility']['insertions']:
            restored = restored.replace(row['text'], '', 1)
        self.assertEqual(without_audio(restored), without_audio(source))
        self.assertIn(MOUNTS, adapted)
        self.assertEqual(review_mounts(source, canvas), proof['mounts'])

    def test_mount_outside_root_two_roots_and_inline_nesting_reject(self) -> None:
        """Mount outside root, two roots and inline nesting reject."""
        source, canvas = nested()
        outside = source.replace(MOUNTS, '', 1).replace('<script>', MOUNTS + '<script>', 1)
        second = source.replace('<script>', '<div id="other" data-composition-id="other" data-width="1080" '
                                'data-height="1920" data-fps="25" data-duration="1"></div><script>', 1)
        inline = source.replace('data-composition-src="compositions/graphic.html" ', '', 1)
        inside_mount = source.replace('data-width="900" data-height="440"></div>',
            'data-width="900" data-height="440"><div data-composition-id="deep" data-composition-src="compositions/deep.html" '
            'data-start="0" data-duration="0.5"></div></div>', 1)
        cases = {'outside the native canvas root': outside, 'one standalone native composition root': second,
                 'nested inline compositions': inline, 'host must be empty': inside_mount}
        for message, changed in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                adapt_html(changed, canvas)

    def test_changed_clock_and_mount_windows_reject(self) -> None:
        """Changed clock and mount windows reject."""
        source, canvas = nested()
        longer = {**canvas, 'totalFrames': 26, 'segments': [{'startFrame': 0, 'endFrameExclusive': 26}]}
        faster = {**canvas, 'frameRate': '30/1', 'totalFrames': 30, 'segments': [{'startFrame': 0, 'endFrameExclusive': 30}]}
        cases = [('HTML canvas clock differs', source.replace('data-duration="1">', 'data-duration="1.04">', 1), canvas),
                 ('HTML canvas clock differs', source, longer), ('HTML canvas clock differs', source, faster),
                 ('does not cover the canvas', source, {**canvas, 'totalFrames': 26}),
                 ('window exceeds the canvas', source.replace('data-start="0.5" data-duration="0.5"',
                                                              'data-start="0.52" data-duration="0.5"', 1), canvas),
                 ('Invalid native media clock', source.replace('data-start="0.5" ', '', 1), canvas)]
        for message, changed, clock in cases:
            with self.subTest(message=message, clock=clock), self.assertRaisesRegex(ValueError, message):
                adapt_html(changed, clock)

    def test_timed_ancestor_unsafe_path_and_duplicate_identity_reject(self) -> None:
        """Timed ancestor, unsafe path and duplicate identity reject."""
        source, canvas = nested()
        timed = source.replace(MOUNTS, f'<div id="scene" data-start="0.2" data-duration="0.8">{MOUNTS}</div>', 1)
        cases = {'root composition clock': timed,
                 'local compositions/': source.replace('compositions/graphic.html', '../graphic.html', 1),
                 'local compositions': source.replace('compositions/graphic.html', 'https://example.test/g.html', 1),
                 'duplicate native composition identity': source.replace('data-composition-id="sn-graphic"',
                                                                        'data-composition-id="native-canvas"', 1)}
        for message, changed in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                adapt_html(changed, canvas)
        untimed = source.replace(MOUNTS, f'<div id="placement" style="position:absolute">{MOUNTS}</div>', 1)
        self.assertEqual(len(adapt_html(untimed, canvas)[1]['mounts']), 2)


class NestedMountBundleTests(unittest.TestCase):
    """The full prepare path copies mounted files and refuses before creating any output."""

    def setUp(self) -> None:
        """Create a checked-looking TEST project with two mounted catalog compositions."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.project = self.root / 'project'
        (self.project / 'assets').mkdir(parents=True); (self.project / 'compositions').mkdir()
        source, canvas = nested()
        (self.project / 'index.html').write_text(source)
        (self.project / 'hyperframes.json').write_text('{"paths":{"blocks":"compositions"}}')
        (self.project / 'assets/source.mp4').write_bytes(b'TEST original picture bytes')
        (self.project / 'assets/source.wav').write_bytes(b'TEST original dialogue')
        (self.project / 'compositions/title.html').write_text(TITLE)
        (self.project / 'compositions/graphic.html').write_text(TITLE.replace('sn-title', 'sn-graphic'))
        (self.project / 'SHORT-PROJECT.json').write_text(json.dumps({'canvas': canvas}))
        self.canvas = canvas
        self.video = self.root / 'review.mp4'; self.video.write_bytes(b'TEST checked encoded MP4')
        self.target = self.root / 'bundle'

    def row(self) -> ReviewComposition:
        """Admit the current TEST project bytes, as read_manifest would after checked delivery."""
        files = {str(file.relative_to(self.project)): digest(file) for file in self.project.rglob('*') if file.is_file()}
        return ReviewComposition('Story', 'TEST story', self.root / 'export', self.project, self.root / 'runtime', files,
                                 {}, {'canvas': self.canvas}, 'index.html', self.video, digest(self.video))

    def prepare(self, row: ReviewComposition) -> tuple[dict, Path]:
        """Run the real prepare() with TEST tools and the admitted row."""
        manifest = self.root / 'manifest.json'; manifest.write_text('{"schemaVersion":1,"compositions":[]}')
        tool = self.root / 'tool'; tool.write_text('TEST tool')
        tools = {name: str(tool) for name in ('node', 'ffmpeg', 'ffprobe', 'browser')}
        with mock.patch.object(bundle, 'read_manifest', return_value=[row]), \
             mock.patch.object(bundle, 'local_environment', return_value=(tools, {})):
            return bundle.prepare(manifest, self.target)

    def test_prepare_publish_and_read_keep_mounted_catalog_files(self) -> None:
        """Prepare publish and read keep mounted catalog files."""
        request, request_file = self.prepare(self.row())
        row = request['compositions'][0]
        self.assertEqual([mount['file'] for mount in row['proof']['mounts']],
                         ['compositions/title.html', 'compositions/graphic.html'])
        studio = Path(row['studio'])
        self.assertEqual((studio / 'compositions/title.html').read_text(), TITLE)
        audio = Path(row['root']) / 'studio-dialogue.m4a'; audio.write_bytes(b'TEST AAC')
        frames = []
        for point in row['frames']:
            image = Path(row['root']) / f'frame-{point["frame"]}.jpg'; image.write_bytes(b'TEST JPEG')
            frames.append({**point, 'path': str(image), 'sha256': digest(image)})
        media = {'id': row['id'], 'videoSha256': row['videoSha256'], 'frames': frames,
                 'audio': {'path': str(audio), 'sha256': digest(audio), 'audioPacketsIdentical': True,
                           'additionalAudioEncodes': 0, 'additionalVideoEncodes': 0}}
        (self.target / 'media-preparation.json').write_text(json.dumps({'status': bundle.STATUS, 'compositions': [media]}))
        pins = {**request['pins'], str(request_file): digest(request_file)}
        record = {'status': bundle.STATUS, 'exitCode': 0, 'cleanup': {'verified': True}, 'leaseCleanupVerified': True,
                  'output': str(self.target / 'media-preparation.json'), 'additionalFilePinsBefore': pins,
                  'additionalFilePinsAfter': pins}
        owner_file = self.target / 'native-review.render.json'; owner_file.write_text(json.dumps(record))
        bundle.publish(request, type('Owner', (), {'result': record, 'path': owner_file})())
        published = bundle.read_bundle(self.target)['compositions'][0]
        self.assertEqual(published['studioState']['status'], 'prepared-files-unchanged')
        index = (studio / 'index.html').read_text()
        self.assertIn(MOUNTS, index)
        self.assertIn('src="assets/studio-dialogue.m4a"', index)

    def test_media_bearing_unlisted_or_changed_mounts_refuse_before_output(self) -> None:
        """Media bearing unlisted or changed mounts refuse before output."""
        graphic = self.project / 'compositions/graphic.html'; original = graphic.read_text()
        cases = {'cannot replace or gate': original.replace('<p>TEST title</p>', '<audio src="assets/x.wav"></audio>'),
                 'mounts another composition': original.replace('<p>TEST title</p>',
                                                               '<div data-composition-src="compositions/x.html"></div>')}
        for message, text in cases.items():
            graphic.write_text(text)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.prepare(self.row())
            self.assertFalse(self.target.exists())
        graphic.write_text(original)
        row = self.row()
        unlisted = {name: sha for name, sha in row.files.items() if name != 'compositions/graphic.html'}
        with self.assertRaisesRegex(ValueError, 'outside the checked export'):
            self.prepare(replace(row, files=unlisted))
        graphic.write_text(original.replace('TEST title', 'TEST changed'))
        with self.assertRaisesRegex(ValueError, 'differs from its checked export'):
            self.prepare(row)
        self.assertFalse(self.target.exists())


if __name__ == '__main__': unittest.main()
