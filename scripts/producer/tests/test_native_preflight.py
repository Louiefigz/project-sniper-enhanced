"""Native static preflight tests: real SDK rules, no video/browser/network work."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import file_hash
from headless.process_runner import ProcessDeadlineError, ProcessOutputLimitError
from studio import native_preflight as native
from studio import native_preflight_inputs as inputs

HTML = '''<!doctype html><html><head><style>body{margin:0;background:#000}
@font-face{font-family:'TestFont';src:url('assets/test.woff2')}
</style><script src="assets/gsap.js"></script></head><body>
<div data-composition-id="test-root" data-width="1920" data-height="1080" data-duration="2">
<div id="box">TEST ONLY</div><img id="mark" src="assets/mark.svg">
</div><script>window.__timelines={};const tl=gsap.timeline({paused:true});
tl.to('#box',{opacity:1,duration:2},0);window.__timelines['test-root']=tl;
</script></body></html>'''


class NativePreflightTests(unittest.TestCase):
    """Only owned TEST sources may be mutated; the linter never executes them."""

    def setUp(self) -> None:
        """Create tiny explicit non-renderable fixtures and use installed Node."""
        temporary = tempfile.TemporaryDirectory(prefix='sniper-preflight-test-', dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.assets = self.project / 'assets'
        self.assets.mkdir(parents=True)
        self.entry = self.project / 'index.html'
        self.entry.write_text(HTML)
        (self.assets / 'gsap.js').write_text('throw Error("TEST source must never execute");')
        (self.assets / 'test.woff2').write_bytes(b'TEST FONT PLACEHOLDER, NOT QUALIFIED FONT DATA')
        (self.assets / 'mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        node = os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')
        self.assertIsNotNone(node, 'Installed local Node is required; never download it')
        environment = patch.dict(os.environ, {'SNIPER_NODE_PATH': str(Path(node).resolve()),
                                              'SECRET_TEST': 'must-not-inherit'})
        environment.start()
        self.addCleanup(environment.stop)

    def execute(self, name: str = 'evidence') -> dict:
        """Run actual installed SDK lint under the existing bounded text runner."""
        return native.preflight(self.project, self.root / name)

    def codes(self, report: dict) -> set[str]:
        """Collect separate native dependency and unchanged SDK findings."""
        sdk = report['sdk']
        findings = list(sdk['dependencyFindings'])
        findings.extend(row for result in sdk['result']['results'] for row in result['result']['findings'])
        return {row['code'] for row in findings}

    def test_static_pass_never_claims_media_quality_or_changes_project(self) -> None:
        """Placeholder fixture success is static success only, with identical inputs."""
        before = inputs.source_state(self.project)
        actual = native.run_text
        def observe(request: native.ProcessRequest) -> object:
            self.assertNotIn('SECRET_TEST', request.environment)
            self.assertLessEqual(request.timeout_seconds, native.MAX_SECONDS)
            return actual(request)
        with patch.object(native, 'run_text', side_effect=observe):
            result = self.execute()
        self.assertEqual(result['status'], 'static-checks-pass')
        self.assertEqual(inputs.source_state(self.project), before)
        for key in ('renderApproved', 'qualityApproved', 'mediaContentQualified'):
            self.assertIs(result[key], False)
        self.assertIs(result['sdk']['codecProbePerformed'], False)
        self.assertEqual(result['sdk']['deniedAttempts'], [])
        self.assertEqual(len(result['nextChecks']), 2)
        self.assertEqual(native.read_completed(self.root / 'evidence')['status'], result['status'])

    def test_missing_font_blocks_before_a_full_render(self) -> None:
        """A declared font URL is not evidence that its bytes are available."""
        (self.assets / 'test.woff2').unlink()
        result = self.execute()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('native_missing_dependency', self.codes(result))

    def test_missing_picture_preserves_the_actual_sdk_error(self) -> None:
        """Extra source checks never replace or weaken official asset rules."""
        (self.assets / 'mark.svg').unlink()
        result = self.execute()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('missing_local_asset', self.codes(result))

    def test_missing_timeline_registry_preserves_sdk_error(self) -> None:
        """No invented fallback timeline can turn malformed source into success."""
        self.entry.write_text(HTML.replace('window.__timelines', 'window.testOnly'))
        self.assertIn('missing_timeline_registry', self.codes(self.execute()))

    def test_remote_dependency_is_reported_without_network(self) -> None:
        """External fonts are not fetched, silently substituted or auto-installed."""
        self.entry.write_text(HTML.replace('assets/test.woff2', 'https://example.invalid/font.woff2'))
        result = self.execute()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('native_nonlocal_dependency', self.codes(result))
        self.assertEqual(result['sdk']['deniedAttempts'], [])

    def test_nested_css_and_sibling_resolution(self) -> None:
        """Use actual CSS import/URL declarations and the owning file's directory."""
        styles = self.project / 'styles'
        styles.mkdir()
        (styles / 'main.css').write_text('@import "child.css";')
        (styles / 'child.css').write_text('@font-face{font-family:Other;src:url("../assets/test.woff2")}')
        self.entry.write_text(HTML.replace('</head>', '<link rel="stylesheet" href="styles/main.css"></head>'))
        self.assertEqual(self.execute()['status'], 'static-checks-pass')
        (styles / 'child.css').write_text('@font-face{font-family:Other;src:url("../assets/missing.woff2")}')
        self.assertEqual(self.execute('missing')['status'], 'blocked')

    def test_nested_template_mount_missing_is_not_silently_skipped(self) -> None:
        """SDK missing-child traversal must see inert nested template content."""
        (self.project / 'compositions').mkdir()
        (self.project / 'compositions/child.html').write_text('''<template>
<div data-composition-id="child" data-width="1920" data-height="1080" data-duration="2">
<div data-composition-src="compositions/missing.html" data-start="0" data-duration="2"></div>
</div></template>''')
        self.entry.write_text(HTML.replace('TEST ONLY', '<div data-composition-src="compositions/child.html" data-start="0" data-duration="2"></div>'))
        self.assertEqual(self.execute()['status'], 'blocked')

    def test_source_mount_escape_refuses_without_reading_outside(self) -> None:
        """No malformed child reference can make the SDK inspect outside HTML."""
        self.entry.write_text(HTML.replace('TEST ONLY', '<div data-composition-src="../outside.html"></div>'))
        with self.assertRaisesRegex(RuntimeError, 'worker refused'):
            self.execute()
        process = json.loads((self.root / 'evidence/process.json').read_text())
        self.assertIn('mount escapes', process['stderr'])

    def test_symlinks_refuse_before_worker_launch(self) -> None:
        """A local-looking dependency must not follow another tree's files."""
        (self.assets / 'linked.svg').symlink_to(self.assets / 'mark.svg')
        with patch.object(native, 'run_text') as run, self.assertRaisesRegex(RuntimeError, 'linked'):
            self.execute()
        run.assert_not_called()

    def test_changed_inode_after_lint_invalidates_success(self) -> None:
        """Same bytes at a replaced path still invalidate this source snapshot."""
        actual = native.run_text
        def replace(request: native.ProcessRequest) -> object:
            result = actual(request)
            replacement = self.project / 'replacement'
            replacement.write_text(self.entry.read_text())
            replacement.replace(self.entry)
            return result
        with patch.object(native, 'run_text', side_effect=replace), self.assertRaisesRegex(RuntimeError, 'changed'):
            self.execute()
        self.assertFalse((self.root / 'evidence/result.json').exists())
        self.assertTrue((self.root / 'evidence/failure.json').exists())


    def test_media_is_metadata_only_and_never_probed(self) -> None:
        """Inert TEST bytes exercise no-probe behavior, never codec qualification."""
        (self.assets / 'test.mp4').write_bytes(b'TEST ONLY: NOT DECODABLE MEDIA')
        self.entry.write_text(HTML.replace('TEST ONLY', '<video id="v" class="clip" '
            'src="assets/test.mp4" data-start="0" data-duration="2" data-track-index="0" muted></video>'))
        result = self.execute()
        self.assertEqual(result['status'], 'static-checks-pass', self.codes(result))
        self.assertEqual(result['sdk']['deniedAttempts'], [])
        state = json.loads((self.root / 'evidence/inputs.json').read_text())
        self.assertIsNone(state['source']['files']['assets/test.mp4']['sha256'])
        self.assertIs(result['mediaContentQualified'], False)

    def test_existing_result_or_project_output_is_never_overwritten(self) -> None:
        """Both previous successful evidence and current project remain unchanged."""
        self.execute()
        original = file_hash(self.root / 'evidence/result.json')
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(file_hash(self.root / 'evidence/result.json'), original)
        with self.assertRaisesRegex(ValueError, 'outside'):
            native.preflight(self.project, self.project / 'evidence')

    def test_worker_timeout_and_output_limit_keep_failure_evidence(self) -> None:
        """Resource or observability failure cannot become a static pass."""
        for exception in (ProcessDeadlineError('TEST timeout'), ProcessOutputLimitError('TEST cap')):
            with patch.object(native, 'run_text', side_effect=exception), self.assertRaises(type(exception)):
                self.execute(type(exception).__name__)
            failure = self.root / type(exception).__name__ / 'failure.json'
            self.assertIs(json.loads(failure.read_text())['renderApproved'], False)

    def test_mixed_counts_sources_and_duplicate_json_fail_closed(self) -> None:
        """The parent consumes observed findings, not a caller's passing boolean."""
        report = self.execute()
        good = report['sdk']
        source = json.loads((self.root / 'evidence/inputs.json').read_text())['source']
        for key, value in (('schemaVersion', True), ('blocked', 0), ('codecProbePerformed', True),
                           ('deniedAttempts', ['fetch']), ('dependencyFindings', None),
                           ('elapsedMs', True), ('elapsedMs', 31000), ('result', [])):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                native._result(json.dumps({**good, key: value}), good['requestSha256'], source)
        bad = copy.deepcopy(good)
        bad['result']['results'][0]['contentHash'] = '0' * 16
        with self.assertRaisesRegex(RuntimeError, 'content'):
            native._result(json.dumps(bad), good['requestSha256'], source)
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            native._result('{"schemaVersion":1,' + json.dumps(good)[1:], good['requestSha256'], source)

    def test_final_publication_cannot_escape_original_deadline(self) -> None:
        """A delayed report retains an overriding failure, not a passing return."""
        actual = native.write_new
        clock = [1000.0]
        def delayed(path: Path, value: dict) -> None:
            actual(path, value)
            if path.name == 'result.json':
                clock[0] = 1031.0
        with patch.object(native.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(native, 'write_new', side_effect=delayed), self.assertRaisesRegex(RuntimeError, 'deadline'):
            self.execute()
        self.assertTrue((self.root / 'evidence/failure.json').exists())
        self.assertFalse((self.root / 'evidence/completion.json').exists())
        pending = json.loads((self.root / 'evidence/result.json').read_text())
        self.assertEqual(pending['status'], 'pending-validation')

    def test_excluded_dependency_is_not_a_bound_project_asset(self) -> None:
        """SDK/cache directories cannot smuggle unobserved styles into a pass."""
        excluded = self.project / 'node_modules'
        excluded.mkdir()
        (excluded / 'unobserved.css').write_text('body{color:blue}')
        self.entry.write_text(HTML.replace('</head>', '<link rel="stylesheet" href="node_modules/unobserved.css"></head>'))
        with self.assertRaisesRegex(RuntimeError, 'worker refused'):
            self.execute()

    def test_file_limit_refuses_before_the_sdk(self) -> None:
        """Bounded static work cannot accidentally traverse a frame-cache tree."""
        with patch.object(inputs, 'MAX_FILES', 2), patch.object(native, 'run_text') as run, \
                self.assertRaisesRegex(RuntimeError, 'inventory exceeds'):
            self.execute()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
