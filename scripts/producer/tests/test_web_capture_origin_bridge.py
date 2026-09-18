"""Bounded subprocess-boundary tests; synthetic bytes never enter media/browser work."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import web_capture


class WebCaptureOriginBridgeTests(unittest.TestCase):
    """The Python bridge may publish only an unchanged, independently read asset binding."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix='sniper-web-origin-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.node = '/test tools/node'

    def output(self, name: str = 'capture') -> Path:
        """Create tiny capture receipts without invoking any acquisition or media tool."""
        directory = self.root / name
        directory.mkdir()
        (directory / 'capture.mp4').write_bytes(b'TEST synthetic bytes, not video')
        (directory / 'capture.json').write_text(json.dumps({'status': 'captured-for-review'}))
        (directory / 'capture.render.json').write_text(json.dumps({'status': 'TEST supervised capture'}))
        return directory

    def adapter(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        """Model a successful adapter and a separate shared-reader process boundary."""
        self.assertEqual(command[0], self.node)
        self.assertEqual(kwargs['cwd'], web_capture.REPO)
        self.assertEqual(kwargs['timeout'], 60)
        self.assertIs(kwargs['check'], True)
        self.assertIs(kwargs['capture_output'], True)
        if '--eval' in command:
            self.assertIn('readNativeAssetOrigin', command[-1])
            candidate = json.loads(str(kwargs['input']))
            origin = Path(candidate['origin']['path'])
            self.assertEqual(web_capture.digest(origin), candidate['origin']['sha256'])
            return subprocess.CompletedProcess(command, 0, stdout='')
        self.assertEqual(command[1:4], ['--import', 'tsx', str(web_capture.REPO / 'scripts/producer/native-short.ts')])
        self.assertEqual(command[4], 'origin-web')
        technical, origin = Path(command[5]), Path(command[6])
        self.assertEqual(technical.name, 'CAPTURE-ASSET.json')
        self.assertEqual(origin, technical.parent / 'ASSET-ORIGIN.json')
        binding = json.loads(technical.read_text())
        self.assertNotIn('origin', binding)
        origin.write_text(json.dumps({'test': 'adapter-owned immutable origin fixture'}))
        candidate = {**binding, 'origin': {'path': str(origin), 'sha256': web_capture.digest(origin)}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(candidate))

    def test_bridge_keeps_frozen_capture_identity_and_verified_origin(self) -> None:
        directory = self.output()
        with patch.object(web_capture.subprocess, 'run', side_effect=self.adapter) as run:
            web_capture.write_binding(directory, self.node)
        self.assertEqual(run.call_count, 2)
        technical = json.loads((directory / 'CAPTURE-ASSET.json').read_text())
        asset = json.loads((directory / 'ASSET.json').read_text())
        self.assertEqual({key: asset[key] for key in technical}, technical)
        self.assertEqual(technical['sha256'], web_capture.digest(directory / 'capture.mp4'))
        self.assertEqual(technical['file'], f"assets/{technical['sha256']}.mp4")
        self.assertEqual(technical['webCapture']['sha256'], web_capture.digest(directory / 'capture.json'))
        self.assertEqual(technical['webCapture']['supervisionSha256'], web_capture.digest(directory / 'capture.render.json'))
        self.assertEqual(asset['origin']['path'], str(directory / 'ASSET-ORIGIN.json'))

    def test_incomplete_capture_never_calls_adapter_or_publishes_binding(self) -> None:
        directory = self.output()
        (directory / 'capture.json').write_text(json.dumps({'status': 'failed'}))
        with patch.object(web_capture.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'incomplete'):
            web_capture.write_binding(directory, self.node)
        run.assert_not_called()
        self.assertFalse((directory / 'CAPTURE-ASSET.json').exists())
        self.assertFalse((directory / 'ASSET.json').exists())

    def test_adapter_failure_propagates_without_final_asset(self) -> None:
        directory = self.output()
        failure = subprocess.CalledProcessError(2, ['TEST adapter'], stderr='TEST origin rejected')
        with patch.object(web_capture.subprocess, 'run', side_effect=failure), self.assertRaises(subprocess.CalledProcessError) as caught:
            web_capture.write_binding(directory, self.node)
        self.assertIs(caught.exception, failure)
        self.assertTrue((directory / 'CAPTURE-ASSET.json').exists())
        self.assertFalse((directory / 'ASSET.json').exists())

    def test_missing_origin_mismatched_binding_and_wrong_path_never_publish(self) -> None:
        variants = ['missing-origin', 'changed-source', 'changed-web-receipt', 'wrong-origin-path', 'extra-field']
        for variant in variants:
            with self.subTest(variant=variant):
                directory = self.output(variant)
                def corrupt(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
                    result = self.adapter(command, **kwargs)
                    value = json.loads(result.stdout)
                    if variant == 'missing-origin':
                        del value['origin']
                    elif variant == 'changed-source':
                        value['sha256'] = '0' * 64
                    elif variant == 'changed-web-receipt':
                        value['webCapture']['sha256'] = '0' * 64
                    elif variant == 'wrong-origin-path':
                        value['origin']['path'] = str(directory / 'unrelated.json')
                    else:
                        value['verified'] = True
                    result.stdout = json.dumps(value)
                    return result
                with patch.object(web_capture.subprocess, 'run', side_effect=corrupt) as run, self.assertRaises(ValueError):
                    web_capture.write_binding(directory, self.node)
                self.assertEqual(run.call_count, 1)
                self.assertFalse((directory / 'ASSET.json').exists())

    def test_shared_origin_reader_failure_prevents_final_asset(self) -> None:
        directory = self.output()
        def reject(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if '--eval' in command:
                raise subprocess.CalledProcessError(1, command, stderr='TEST changed origin evidence')
            return self.adapter(command, **kwargs)
        with patch.object(web_capture.subprocess, 'run', side_effect=reject) as run, self.assertRaises(subprocess.CalledProcessError):
            web_capture.write_binding(directory, self.node)
        self.assertEqual(run.call_count, 2)
        self.assertFalse((directory / 'ASSET.json').exists())

    def test_malformed_adapter_json_does_not_leave_empty_asset_file(self) -> None:
        directory = self.output()
        result = subprocess.CompletedProcess(['TEST'], 0, stdout='{bad json')
        with patch.object(web_capture.subprocess, 'run', return_value=result), self.assertRaises(json.JSONDecodeError):
            web_capture.write_binding(directory, self.node)
        self.assertFalse((directory / 'ASSET.json').exists())


if __name__ == '__main__':
    unittest.main()
