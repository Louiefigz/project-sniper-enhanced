"""Completed SDK picture recovery uses tiny evidence fixtures, never media jobs."""
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from studio import native_short_sdk_picture_reuse as sdk
from studio import native_short_picture_reuse as reuse
from studio import native_short_autoresume as automatic
from studio.native_runtime import digest
import test_native_short_picture_reuse as batch_fixture
from test_native_short_picture_reuse import write_json


def traces(count: int) -> str:
    """Represent one SDK job's independently retained complete trace."""
    rows = [
        {'phase':'pipeline','message':'started','format':'mp4','quality':'high','requestedWorkers':1,'forceScreenshot':True},
        {'phase':'compile','message':'composition metadata resolved','width':1080,'height':1920,'deviceScaleFactor':1},
        {'phase':'capture_streaming','status':'end','totalFrames':count,'framesCompleted':count,
         'captureMode':'screenshot','captureOperation':'encode','elapsedMs':1000},
        {'phase':'assemble','status':'end','totalFrames':count,'framesCompleted':count,
         'captureMode':'screenshot','captureOperation':'encode','elapsedMs':1100},
        {'phase':'pipeline','message':'artifact validated','elapsedMs':1200}]
    transport = {'event':'close','closed':True,'failed':False,'errors':0,'aborted':0,'rejected':0,
                 'entries':0,'activeStreams':0,'activeSourceDescriptors':0,'requests':count,'completed':count,
                 'mode':'same-origin-url'}
    return '\n'.join('[INFO] [Render:trace] '+json.dumps({'renderJobId':'TEST-JOB', **row}) for row in rows) \
        + '\n[NativeFrameTransport] '+json.dumps(transport)+'\n'


class NativeSdkPictureReuseTests(unittest.TestCase):
    """Exercise the shared CLI donor dispatch and every source preservation boundary."""

    def setUp(self) -> None:
        self.fixture = batch_fixture.NativeShortPictureReuseTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.enterContext(patch.object(sdk, 'STUDIO', f.studio))
        interpreter = f.root / 'python'
        interpreter.write_text('TEST ONLY interpreter')
        f.previous['pins'][str(interpreter)] = digest(interpreter)
        for name in sdk.PICTURE_CODE:
            file = f.studio / name
            if not file.exists():
                file.write_text('TEST ONLY SDK picture control')
            f.previous['pins'][str(file)] = digest(file)
        f.previous['captureMode'] = sdk.MODE
        write_json(f.donor / 'export-request.json', f.previous)
        f.make_supervision()
        f.pipeline.update(exitCode=1, pid=10, output=str(f.donor/'review.mp4'), logPath=str(f.donor/'pipeline.render.log'),
                          ownerIdentities=[{'pid':10,'pgid':10,'parent_pid':9,'started':'TEST identity'}],
                          args=['/usr/bin/sandbox-exec','-f',str(f.studio/'native_localhost_only.sb'),str(interpreter),
                                str(f.studio/'native_short_worker.py'),str(f.donor/'export-request.json'),'render'])
        write_json(f.donor/'pipeline.render.json', f.pipeline)
        (f.donor/'pipeline.render.log').write_text(traces(2))
        (f.donor/'audio').mkdir()
        self.audio = {'scope':'native-dialogue-audio-qualification-only','status':'failed','error':'TEST audio QC failed',
                      'inputPictureSha256':f.picture['sha256'],'additionalPictureEncodes':0,
                      'picture':{'picturePacketsIdentical':True,'picturePackets':2,'pictureTimeBase':'1/12800',
                                 'pictureSourceSha256':f.picture['sha256']},
                      'audioClock':{'presentedSamples':3840},'audioQuality':[{'status':'fail'}]}
        write_json(f.donor/'audio/receipt.json', self.audio)
        write_json(f.donor/'render-failure.json', {'status':'failed','error':self.audio['error']})

    def request(self, project: Path | None = None) -> dict:
        """Collect the same dispatch-admitted pins used before native supervision."""
        f = self.fixture
        project = project or f.project
        return {**f.previous,'project':str(project),'output':str(f.output),'pictureDonor':str(f.donor),
                'pins':reuse.picture_reuse_pins(project, f.donor)}

    def revised_project(self, change: dict) -> Path:
        """Create an immutable sibling with its own exact updated manifest."""
        project = self.fixture.root/'project-audio-02'
        shutil.copytree(self.fixture.project, project)
        plan = json.loads((project/'SHORT-PROJECT.json').read_text())
        plan.update(change)
        write_json(project/'SHORT-PROJECT.json', plan)
        manifest = json.loads((project/'PROJECT-MANIFEST.json').read_text())
        for row in manifest['files']:
            row['sha256'] = digest(project/row['file'])
        write_json(project/'PROJECT-MANIFEST.json', manifest)
        return project

    def test_exact_sdk_picture_copies_and_preserves_failed_donor(self) -> None:
        f = self.fixture
        before = {str(p):digest(p) for p in f.donor.rglob('*') if p.is_file()}
        result = reuse.reuse_native_picture(self.request())
        self.assertEqual(result['pictureMode'], 'sdk-streaming')
        self.assertFalse(result['pictureRenderedAgain'])
        self.assertEqual(digest(f.output/'picture.mp4'), f.picture['sha256'])
        self.assertEqual(before, {str(p):digest(p) for p in f.donor.rglob('*') if p.is_file()})
        self.assertFalse((f.donor/'render-stage.json').exists())

    def test_automatic_discovery_reaches_the_real_sdk_picture_proof_reader(self) -> None:
        """No donor flag is required, and the actual SDK proof still authorizes the copy."""
        f = self.fixture
        write_json(f.donor / 'delivery.json', {'status': 'failed', 'completedAt': '2026-09-16T12:00:00Z'})
        current = {**f.previous, 'output': str(f.output), 'pins': dict(f.previous['pins'])}
        with patch.object(automatic, 'candidate_attempts', return_value=[f.donor]), \
                patch.object(automatic, 'STUDIO', f.studio), \
                patch('sys.executable', f.pipeline['args'][3]):
            selected = automatic.recover_automatically(current)
        self.assertEqual(selected['recoverySelection']['reused'], 'picture')
        self.assertEqual(selected['pictureDonor'], str(f.donor))
        self.assertFalse(reuse.reuse_native_picture(selected)['pictureRenderedAgain'])

    def test_signal_failure_before_audio_quality_keeps_proved_picture(self) -> None:
        """The real local-signal gate precedes audioQuality; its failure must not lose picture."""
        audio = {**self.audio, 'signal': {'status': 'local-signal-checks-failed',
                                         'passed': False, 'inputsStable': True}}
        audio.pop('audioQuality')
        write_json(self.fixture.donor / 'audio/receipt.json', audio)
        self.assertIn(str(self.fixture.donor / 'picture.mp4'), self.request()['pins'])
        audio['signal']['inputsStable'] = False
        write_json(self.fixture.donor / 'audio/receipt.json', audio)
        with self.assertRaisesRegex(ValueError, 'missing failed audio'):
            self.request()

    def test_qualified_audio_before_color_failure_keeps_proved_picture(self) -> None:
        """A later metadata failure cannot require re-encoding an already checked picture."""
        audio = {**self.audio, 'status': 'audio-qualified', 'audioQuality': [{'status': 'pass'}],
                 'signal': {'passed': True, 'inputsStable': True}}
        audio.pop('error')
        write_json(self.fixture.donor / 'audio/receipt.json', audio)
        write_json(self.fixture.donor / 'render-failure.json', {'status': 'failed', 'error': 'TEST metadata failure'})
        self.assertIn(str(self.fixture.donor / 'picture.mp4'), self.request()['pins'])
        audio['signal']['passed'] = False
        write_json(self.fixture.donor / 'audio/receipt.json', audio)
        with self.assertRaisesRegex(ValueError, 'missing qualified audio'):
            self.request()

    def test_only_audio_finishing_revision_and_audio_implementation_are_allowed(self) -> None:
        project = self.revised_project({'audioFinishing':{'schemaVersion':1,'audioEnhance':{'preset':'voice','humFrequency':181}}})
        self.fixture.audio.write_text('TEST ONLY new audio mastering code')
        result = reuse.reuse_native_picture(self.request(project))
        self.assertEqual(result['originalProject'], str(self.fixture.project))
        self.assertEqual(result['project'], str(project))

    def test_changed_clock_or_strategy_cannot_be_an_audio_revision(self) -> None:
        for change in ({'canvas':{'frameRate':'25/1','totalFrames':3}}, {'strategy':{'schemaVersion':2,'changed':True}}):
            project = self.revised_project(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'visual strategy'):
                self.request(project)
            shutil.rmtree(project)

    def test_changed_visual_html_and_asset_rejected(self) -> None:
        project = self.revised_project({'audioFinishing':{'schemaVersion':1}})
        (project/'index.html').write_text('TEST changed picture')
        manifest = json.loads((project/'PROJECT-MANIFEST.json').read_text())
        for row in manifest['files']:
            row['sha256'] = digest(project/row['file'])
        write_json(project/'PROJECT-MANIFEST.json', manifest)
        with self.assertRaisesRegex(ValueError, 'payload changed'):
            self.request(project)
        self.fixture.source.write_bytes(b'CHANGED source')
        with self.assertRaisesRegex(ValueError, 'changed input'):
            self.request()

    def test_failed_incomplete_or_mixed_sdk_trace_rejected(self) -> None:
        path = self.fixture.donor/'pipeline.render.log'
        original = path.read_text()
        changes = [('"framesCompleted": 2', '"framesCompleted": 1'),
                   ('artifact validated','artifact incomplete'),('"errors": 0','"errors": 1'),
                   ('"width": 1080','"width": 1920'),('"quality": "high"','"quality": "low"')]
        for old, new in changes:
            path.write_text(original.replace(old,new))
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.request()
        path.write_text(original+original)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.request()

    def test_post_picture_proof_and_cleanup_are_required(self) -> None:
        f = self.fixture
        for change in ({'picture':{}},{'inputPictureSha256':'a'*64},{'audioClock':{'presentedSamples':1}},
                       {'audioQuality':[]},{'status':'audio-qualified'}):
            write_json(f.donor/'audio/receipt.json', {**self.audio,**change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.request()
        write_json(f.donor/'audio/receipt.json', self.audio)
        for change in ({'abortReason':'disk'},{'leaseCleanupVerified':False},{'ownerIdentities':[]},
                       {'additionalFilePinsAfter':{}},{'exitCode':0},{'args':['TEST invented command']}):
            write_json(f.donor/'pipeline.render.json', {**f.pipeline,**change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.request()

    def test_picture_or_evidence_mutation_and_unpinned_receipt_rejected(self) -> None:
        f = self.fixture
        request = self.request()
        del request['pins'][str(f.donor/'audio/receipt.json')]
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            reuse.reuse_native_picture(request)
        request = self.request()
        (f.donor/'picture.mp4').write_bytes(b'TEST changed encoded picture')
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            reuse.reuse_native_picture(request)
        self.assertFalse((f.output/'picture.mp4').exists())

    def test_current_runtime_mode_and_output_overlap_rejected(self) -> None:
        request = self.request()
        for change in ({'runtime':'/TEST/different'},{'captureMode':'cached-native-batches'},
                       {'output':str(self.fixture.donor)},{'output':str(self.fixture.root)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                reuse.reuse_native_picture({**request,**change})


if __name__ == '__main__':
    unittest.main()
