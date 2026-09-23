"""Adversarial static-only fixtures for native dependencies and completion."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_native_preflight as fixtures

HTML, inputs, native = fixtures.HTML, fixtures.inputs, fixtures.native


class NativePreflightEdgeTests(unittest.TestCase):
    """Reuse fixture setup, not the original test methods or any media jobs."""

    setUp = fixtures.NativePreflightTests.setUp
    execute = fixtures.NativePreflightTests.execute
    codes = fixtures.NativePreflightTests.codes

    def test_declarative_dependency_holes_cannot_pass(self) -> None:
        """Remote mounts, SVG dependencies and unsupported responsive forms block."""
        declarations = [
            '<div data-composition-src="https://example.invalid/scene.html"></div>',
            '<div data-composition-src="{{scene}}"></div>',
            '<div data-composition-src="data:text/html,unqualified"></div>',
            '<div data-composition-src=""></div>',
            '<div data-composition-src="#scene"></div>',
            '<svg><image href="missing.png"/></svg>',
            '<svg><use xlink:href="missing.svg#shape"/></svg>',
            '<img srcset="missing.png 2x">',
            '<div style="background:image-set(\'missing.png\' 2x)"></div>',
        ]
        for index, declaration in enumerate(declarations):
            with self.subTest(declaration=declaration):
                self.entry.write_text(HTML.replace('TEST ONLY', declaration))
                result = self.execute(f'declaration-{index}', renew_sources=True)
                self.assertEqual(result['status'], 'blocked')
                self.assertTrue(result['sdk']['dependencyFindings'])
                self.assertEqual(result['sdk']['deniedAttempts'], [])

    def test_uppercase_css_urls_and_imports_are_checked(self) -> None:
        """CSS names and URL functions are case-insensitive, including fonts."""
        (self.project / 'MAIN.CSS').write_text('@IMPORT "child.CSS";')
        child = self.project / 'child.CSS'
        child.write_text('@font-face{font-family:Edge;src:URL("assets/test.woff2")}')
        self.entry.write_text(HTML.replace('</head>', '<link rel="stylesheet" href="MAIN.CSS"></head>'))
        self.assertEqual(self.execute(renew_sources=True)['status'], 'static-checks-pass')
        child.write_text('@font-face{font-family:Edge;src:URL("missing.woff2")}')
        self.assertIn('native_missing_dependency', self.codes(self.execute('missing', renew_sources=True)))

    def test_unlinted_html_is_unsupported_not_silently_successful(self) -> None:
        """Files outside the SDK composition scan must be identified as unlinted."""
        (self.project / 'outside.HTML').write_text(HTML)
        self.entry.write_text(HTML.replace('TEST ONLY', '<div data-composition-src="outside.HTML"></div>'))
        result = self.execute(renew_sources=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('native_unlinted_html', self.codes(result))

    def test_nonhtml_mount_is_not_covered_by_existence_only(self) -> None:
        """Valid-looking HTML behind another extension does not escape coverage."""
        (self.project / 'scene.txt').write_text(HTML)
        self.entry.write_text(HTML.replace('TEST ONLY', '<div data-composition-src="scene.txt"></div>'))
        self.assertIn('native_unsupported_dependency', self.codes(self.execute(renew_sources=True)))

    def test_parent_checks_complete_html_coverage(self) -> None:
        """A worker cannot hide an omitted HTML row by returning consistent totals."""
        result = self.execute()['sdk']
        source = inputs.source_state(self.project)
        source['files']['missing.HTML'] = source['files']['index.html']
        with self.assertRaisesRegex(RuntimeError, 'coverage'):
            native._result(json.dumps(result), result['requestSha256'], source)

    def test_completion_requires_matching_result_and_no_failure(self) -> None:
        """A status field alone is never proof that preflight completed."""
        self.execute()
        output = self.root / 'evidence'
        receipt = output / 'completion.json'
        original = receipt.read_text()
        receipt.unlink()
        with self.assertRaises(FileNotFoundError):
            native.read_completed(output)
        receipt.write_text(original.replace('static-checks-pass', 'blocked'))
        with self.assertRaisesRegex(RuntimeError, 'completion'):
            native.read_completed(output)
        receipt.write_text(original)
        (output / 'failure.json').write_text('{"status":"failed"}')
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            native.read_completed(output)

    def test_request_change_at_publication_cannot_complete(self) -> None:
        """Request identity is retained until final completion, not only worker exit."""
        actual = native.write_new
        def mutate(path: Path, value: dict) -> None:
            actual(path, value)
            if path.name == 'result.json':
                request = path.parent / 'request.json'
                request.write_text(request.read_text() + '\n')
        with patch.object(native, 'write_new', side_effect=mutate), self.assertRaisesRegex(RuntimeError, 'request changed'):
            self.execute()
        self.assertFalse((self.root / 'evidence/completion.json').exists())

    def test_static_guard_blocks_filesystem_writes(self) -> None:
        """Even a trusted linter update cannot silently write through normal fs APIs."""
        target = self.root / 'must-not-exist'
        module = native.ROOT / 'scripts/producer/graphics/comp_capability_lint.mjs'
        code = (f'import {{forbidWrites,attempts}} from {json.dumps(module.as_uri())};'
                'import fs from "node:fs";forbidWrites();'
                f'try{{fs.writeFileSync({json.dumps(str(target))},"denied");}}catch{{}}'
                'process.stdout.write(JSON.stringify(attempts));')
        request = native.ProcessRequest((os.environ['SNIPER_NODE_PATH'],
            '--input-type=module', '-e', code), '', str(native.ROOT), native.lint._environment(self.root), 10)
        result = native.run_text(request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['fs.writeFileSync'])
        self.assertFalse(target.exists())

    def test_late_completion_receipt_cannot_escape_deadline(self) -> None:
        """A late final receipt is overridden by failure and refused by the reader."""
        actual = native.write_new
        clock = [1000.0]
        def delayed(path: Path, value: dict) -> None:
            actual(path, value)
            if path.name == 'completion.json':
                clock[0] = 1031.0
        with patch.object(native.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(native, 'write_new', side_effect=delayed), self.assertRaisesRegex(RuntimeError, 'deadline'):
            self.execute()
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            native.read_completed(self.root / 'evidence')


if __name__ == '__main__':
    unittest.main(verbosity=2)
