"""Small filesystem contracts for native review packages; no media processes."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import native_review_bundle as bundle
from studio import native_review_contract as contract
from studio.native_review_contract import ReviewComposition
from studio.native_review_media import extract_audio, extract_frames
from studio.native_runtime import digest
from test_native_review_html import fixture


class NativeReviewBundleTests(unittest.TestCase):
    """Copy, mutation and manifest tests use the real file-copy and HTML transforms."""

    def setUp(self) -> None:
        """Create isolated source files and evidence for the test."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        project = self.root / 'project'; project.mkdir(); (project / 'assets').mkdir()
        source, canvas = fixture('30000/1001', 18000, 'long-wide-example')
        (project / 'episode.html').write_text(source)
        (project / 'hyperframes.json').write_text('{"media":{"autoProxy":true}}')
        (project / 'assets/source.mp4').write_bytes(b'TEST original picture bytes')
        (project / 'assets/source.wav').write_bytes(b'TEST original dialogue')
        (project / 'LONG-PROJECT.json').write_text(json.dumps({'canvas': canvas}))
        files = {str(file.relative_to(project)): digest(file) for file in project.rglob('*') if file.is_file()}
        (project / 'PROJECT-MANIFEST.json').write_text(json.dumps({'files': [{'file': n, 'sha256': h} for n, h in files.items()]}))
        files['PROJECT-MANIFEST.json'] = digest(project / 'PROJECT-MANIFEST.json')
        video = self.root / 'review.mp4'; video.write_bytes(b'TEST checked encoded MP4')
        self.row = ReviewComposition('CustomerStory', '<Customer & Story>', self.root / 'export', project,
            self.root / 'runtime', files, {}, {'canvas': canvas}, 'episode.html', video, digest(video))
        self.output = self.root / 'bundle'; self.output.mkdir()

    def test_wide_long_canvas_clone_and_local_page_keep_original_bytes(self) -> None:
        """Wide long canvas clone and local page keep original bytes."""
        row = bundle.clone_composition(self.row, self.output)
        self.assertEqual(row['samples'], 28828800)
        for name, expected in self.row.files.items():
            self.assertEqual(digest(self.row.project / name), expected)
        config = json.loads((Path(row['studio']) / 'hyperframes.json').read_text())
        self.assertFalse(config['media']['autoProxy'])
        self.assertIn('&lt;Customer &amp; Story&gt;', bundle.local_page([row]))
        self.assertIn('media/CustomerStory.mp4', bundle.local_page([row]))
        player = bundle.PLAYER.read_text().replace('export class SelectionPlayback', 'class SelectionPlayback', 1)
        self.assertIn(player, bundle.local_page([row]))
        self.assertIn('playback.reload()', bundle.local_page([row]))
        self.assertNotIn('studio/CustomerStory/episode.html', bundle.local_page([row]))
        with self.assertRaises(FileExistsError): bundle.clone_composition(self.row, self.output)

    def test_changed_source_during_copy_rejects(self) -> None:
        """Changed source during copy rejects."""
        copy = bundle.copy_picture
        def mutate(source: Path, target: Path, expected: str) -> None:
            """Change the source before the checked copy to exercise rejection."""
            if source.name == 'episode.html': source.write_text('changed HTML')
            copy(source, target, expected)
        with mock.patch.object(bundle, 'copy_picture', side_effect=mutate), self.assertRaises(ValueError):
            bundle.clone_composition(self.row, self.output)

    def test_canonical_project_paths_reject_links_and_traversal(self) -> None:
        """Canonical project paths reject links and traversal."""
        source = self.row.project / 'assets/source.mp4'
        (self.row.project / 'linked').symlink_to(source)
        for name in ['../review.mp4', str(source), 'linked', 'assets/missing.mp4']:
            with self.subTest(name=name), self.assertRaises((ValueError, FileNotFoundError)):
                contract.relative_file(self.row.project, name)

    def test_manifest_duplicates_and_unrecognized_fields_fail_before_admission(self) -> None:
        """Manifest duplicates and unrecognized fields fail before admission."""
        file = self.root / 'manifest.json'
        for value in [{'schemaVersion': 1, 'compositions': [{'id': 'Story'}, {'id': 'story'}]},
                      {'schemaVersion': True, 'compositions': []}, {'schemaVersion': 1, 'compositions': [], 'extra': True}]:
            file.write_text(json.dumps(value))
            with mock.patch.object(contract, 'read_composition') as read, self.assertRaises(ValueError):
                contract.read_manifest(file)
            read.assert_not_called()

    def test_publish_keeps_exact_video_and_refuses_modified_fork(self) -> None:
        """Publish keeps exact video and refuses modified fork."""
        row = bundle.clone_composition(self.row, self.output)
        root = Path(row['root']); audio = root / 'studio-dialogue.m4a'; audio.write_bytes(b'TEST AAC packets')
        media = {'id': row['id'], 'videoSha256': row['videoSha256'], 'frames': [],
                 'audio': {'path': str(audio), 'sha256': digest(audio), 'audioPacketsIdentical': True,
                           'additionalAudioEncodes': 0, 'additionalVideoEncodes': 0}}
        row['frames'] = []; (self.output / 'media').mkdir()
        before = (Path(row['studio']) / row['entry']).read_bytes()
        (Path(row['studio']) / row['entry']).write_text('changed editable HTML')
        with self.assertRaises(ValueError): bundle.publish_composition(row, media, self.output)
        (Path(row['studio']) / row['entry']).write_bytes(before)
        result = bundle.publish_composition(row, media, self.output)
        self.assertEqual(Path(result['localVideo']).read_bytes(), self.row.video.read_bytes())
        self.assertFalse(result['browserPlaybackVerified'] or result['humanListeningApproved'])
        self.assertEqual((Path(result['studio']) / 'assets/studio-dialogue.m4a').read_bytes(), audio.read_bytes())

    def test_fractional_frame_rate_uses_frame_indices_in_one_decode(self) -> None:
        """Fractional frame rate uses frame indices in one decode."""
        row = bundle.clone_composition(self.row, self.output)
        calls = []
        def fake_run(command: list[str]) -> bytes:
            """Write deterministic test output without launching media tools."""
            calls.append(command)
            for index in range(len(row['frames'])):
                (Path(row['root']) / 'encoded-frames' / f'frame-{index+1:08d}.jpg').write_bytes(b'TEST JPEG')
            return b''
        with mock.patch('studio.native_review_media.run', side_effect=fake_run):
            frames = extract_frames(row, {'ffmpeg': 'TEST ffmpeg'})
        self.assertEqual(len(calls), 1)
        self.assertNotIn('-ss', calls[0])
        self.assertEqual([point['frame'] for point in frames], [point['frame'] for point in row['frames']])

    def test_complete_bundle_receipt_checks_publication_and_preserves_edits(self) -> None:
        """Complete bundle receipt checks publication and preserves edits."""
        target = self.root / 'complete-bundle'; manifest = self.root / 'manifest.json'
        manifest.write_text('{"schemaVersion":1,"compositions":[]}')
        executable = self.root / 'tool'; executable.write_text('TEST tool')
        tools = {name: str(executable) for name in ('node', 'ffmpeg', 'ffprobe', 'browser')}
        with mock.patch.object(bundle, 'read_manifest', return_value=[self.row]), \
             mock.patch.object(bundle, 'local_environment', return_value=(tools, {})):
            request, request_file = bundle.prepare(manifest, target)
        media = []
        for row in request['compositions']:
            root = Path(row['root']); audio = root / 'studio-dialogue.m4a'; audio.write_bytes(b'TEST AAC')
            frames = []
            for point in row['frames']:
                image = root / f'frame-{point["frame"]}.jpg'; image.write_bytes(b'TEST JPEG')
                frames.append({**point, 'path': str(image), 'sha256': digest(image)})
            media.append({'id': row['id'], 'videoSha256': row['videoSha256'], 'frames': frames,
                'audio': {'path': str(audio), 'sha256': digest(audio), 'audioPacketsIdentical': True,
                          'additionalAudioEncodes': 0, 'additionalVideoEncodes': 0}})
        (target / 'media-preparation.json').write_text(json.dumps({'status': bundle.STATUS, 'compositions': media}))
        pins = {**request['pins'], str(request_file): digest(request_file)}
        record = {'status': bundle.STATUS, 'exitCode': 0, 'cleanup': {'verified': True}, 'leaseCleanupVerified': True,
                  'output': str(target / 'media-preparation.json'), 'additionalFilePinsBefore': pins, 'additionalFilePinsAfter': pins}
        owner_file = target / 'native-review.render.json'; owner_file.write_text(json.dumps(record))
        owner = type('Owner', (), {'result': record, 'path': owner_file})()
        result = bundle.publish(request, owner)
        prepared = bundle.read_bundle(target)
        self.assertEqual(prepared['localReviewSha256'], result['localReviewSha256'])
        self.assertEqual(prepared['compositions'][0]['studioState']['status'], 'prepared-files-unchanged')
        studio = Path(result['compositions'][0]['studio']); (studio / self.row.entry).write_text('User editable changes')
        edited = bundle.read_bundle(target)['compositions'][0]
        self.assertEqual(edited['studioState']['changedOrMissingFiles'], ['episode.html'])
        self.assertEqual(edited['localVideoStatus'], 'checked-bytes-unchanged')
        self.assertFalse(edited['studioState']['exportConsistencyVerified'])
        Path(result['compositions'][0]['localVideo']).write_bytes(b'changed video')
        with self.assertRaises(ValueError): bundle.read_bundle(target)

    def test_open_uses_managed_studio_and_reports_edits_without_approving_playback(self) -> None:
        """Managed preview opens edited files while preserving the separate MP4 status."""
        state = {'status': 'edited-since-preparation', 'exportConsistencyVerified': False}
        row = {'id': 'example', 'studio': '/TEST/studio', 'studioState': state,
               'localVideoStatus': 'checked-bytes-unchanged'}
        preview = mock.Mock(); preview.to_json.return_value = {'url': 'http://localhost:3991'}
        with mock.patch.object(bundle, 'read_bundle', return_value={'runtime': '/TEST/runtime', 'compositions': [row]}), \
             mock.patch('studio.native_runtime.install_runtime', return_value=Path('/TEST/runtime')), \
             mock.patch('studio.managed_preview.open_preview', return_value=preview) as opened:
            result = bundle.open_bundle(self.output, 'example')
        opened.assert_called_once_with('/TEST/studio')
        self.assertEqual(result['surface'], 'managed-hyperframes-studio')
        self.assertEqual(result['studioState'], state)
        self.assertFalse(result['browserPlaybackVerified'])

    def test_visible_studio_additions_are_reported_but_runtime_caches_are_ignored(self) -> None:
        """User assets change editable status while hidden Studio cache files do not."""
        row = bundle.clone_composition(self.row, self.output); studio = Path(row['studio'])
        (studio / '.studio-cache').mkdir(); (studio / '.studio-cache/thumbnail.jpg').write_bytes(b'cache')
        self.assertEqual(bundle.studio_state(row)['status'], 'prepared-files-unchanged')
        (studio / 'assets/user-logo.svg').write_text('<svg/>')
        state = bundle.studio_state(row)
        self.assertEqual(state['addedFiles'], ['assets/user-logo.svg'])
        self.assertTrue(state['newExportRequiredForEdits'])

    def test_packet_copy_rejects_changed_audio_payload(self) -> None:
        """Packet copy rejects changed audio payload."""
        row = bundle.clone_composition(self.row, self.output)
        target = Path(row['root']) / 'studio-dialogue.m4a'
        def fake_run(command: list[str]) -> bytes:
            """Write deterministic test output without launching media tools."""
            target.write_bytes(b'TEST AAC')
            return b'{"streams":[{"codec_type":"audio"}]}'
        with mock.patch('studio.native_review_media.run', side_effect=fake_run), \
             mock.patch('studio.native_review_media.exact_aac_audio_clock', return_value={'samples': row['samples']}), \
             mock.patch('studio.native_review_media.packet_signature', side_effect=['original', 'changed']), \
             self.assertRaisesRegex(ValueError, 'packets'):
            extract_audio(row, {'ffmpeg': 'TEST ffmpeg', 'ffprobe': 'TEST ffprobe'})


if __name__ == '__main__': unittest.main()
