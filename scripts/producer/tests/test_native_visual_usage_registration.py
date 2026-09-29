"""Automatic Short/Long usage registration boundary tests; no media is read."""
from __future__ import annotations

import ast
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import file_hash
from studio.native_runtime import digest
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_visual_usage_registration import (
    REGISTRATION_FILE, VisualUsageRegistrationError,
    register_completed_visual_usage, usage_implementation_files,
)

REPO = Path(__file__).resolve().parents[3]


def local_python_closure(entries: list[Path]) -> set[Path]:
    """Resolve repo-local static Python imports for the registration boundary."""
    seen: set[Path] = set()
    pending = [file.resolve() for file in entries]
    while pending:
        file = pending.pop()
        if file in seen or not file.is_file():
            continue
        seen.add(file)
        for node in ast.walk(ast.parse(file.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f'{node.module}.{alias.name}'
                    for alias in node.names if alias.name != '*')]
            for name in names:
                parts = name.split('.')
                for root in (REPO, REPO / 'scripts/producer'):
                    candidates = [root.joinpath(*parts).with_suffix('.py'),
                                  root.joinpath(*parts, '__init__.py')]
                    candidates += [root.joinpath(*parts[:depth], '__init__.py')
                                   for depth in range(1, len(parts))]
                    pending.extend(item.resolve() for item in candidates if item.is_file())
    return seen


def write_json(file: Path, value: dict) -> None:
    """Write bounded TEST evidence without claiming a production registration."""
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value) + '\n')


class RegistrationFixture:
    """Stage the small immutable graph used by the post-QC registration caller."""

    def __init__(self, root: Path, mode: str) -> None:
        self.mode, self.root = mode, root
        self.producer = root / 'source-project/producer'
        self.project = root / f'native-{mode}'
        self.output = root / f'checked-{mode}'
        self.producer.mkdir(parents=True)
        self.project.mkdir()
        self.output.mkdir()
        lane = 'native-longform' if mode == 'long' else 'native-shorts'
        name = 'LONG-REQUEST.json' if mode == 'long' else 'SHORT-REQUEST.json'
        self.packet = self.producer / lane / 'requests/request-hash' / name
        packet = {'schemaVersion': 1}
        if mode == 'long':
            packet['producerDir'] = str(self.producer)
        write_json(self.packet, packet)
        self.node = root / 'node'
        self.node.write_text('TEST pinned node, never executed')
        self.plan_file = self.project / ('LONG-PROJECT.json' if mode == 'long'
                                         else 'SHORT-PROJECT.json')
        write_json(self.plan_file, {'schemaVersion': 2, 'visualPlan': {'schemaVersion': 1},
            'requestPacket': {'path': str(self.packet), 'sha256': file_hash(self.packet)}})
        self.pins = {str(file): digest(file) for file in usage_implementation_files()}
        self.pins.update({str(self.node): digest(self.node),
            str(self.plan_file): digest(self.plan_file), str(self.packet): digest(self.packet)})
        self.request = {'schemaVersion': 1, 'project': str(self.project),
            'output': str(self.output), 'tools': {'node': str(self.node)},
            'pins': self.pins, **({'adapter': 'native-long'} if mode == 'long' else {})}
        write_json(self.output / 'export-request.json', self.request)
        self.status = f'native-{mode}-checked-for-review'
        write_json(self.output / 'delivery.json', {'status': self.status,
            'humanApproved': False, 'completedAt': '2026-09-26T12:00:00Z'})

    def successful_child(self, command: list[str], **_options: object) -> subprocess.CompletedProcess:
        """Model the exact CLI's receipt and immutable export-side registration."""
        self.assert_command(command)
        receipt = self.producer / '.sniper-visual-usage' / f'{self.mode}-receipt.json'
        value = {'digest': 'd' * 64, 'mode': self.mode, 'humanApprovalClaim': False}
        if not receipt.exists():
            write_json(receipt, value)
        sidecar = self.output / REGISTRATION_FILE
        registration = {'schemaVersion': 1, 'kind': 'native-visual-usage-registration',
            'status': 'native-visual-usage-registered', 'humanApprovalClaim': False,
            'producerDir': str(self.producer), 'projectDir': str(self.project),
            'exportDir': str(self.output),
            'delivery': {'path': str(self.output / 'delivery.json'),
                         'sha256': file_hash(self.output / 'delivery.json')},
            'receipt': {'path': str(receipt), 'sha256': file_hash(receipt),
                        'digest': value['digest']}, 'projectId': f'TEST-{self.mode}'}
        if not sidecar.exists():
            write_json(sidecar, registration)
        result = {'status': 'native-visual-usage-registered', 'humanApprovalClaim': False,
            'receipt': str(receipt), 'digest': value['digest'],
            'project': {'projectId': f'TEST-{self.mode}'},
            'registration': {'path': str(sidecar), 'sha256': file_hash(sidecar)}}
        return subprocess.CompletedProcess(command, 0, json.dumps(result).encode(), b'')

    def assert_command(self, command: list[str]) -> None:
        """Require producer identity to come from the bound request lane."""
        if command[-3:] != [str(self.producer), str(self.project), str(self.output)]:
            raise AssertionError(f'Unexpected registration command: {command}')


class NativeVisualUsageRegistrationTests(unittest.TestCase):
    """Both routes fail closed and can recover idempotently from preserved output."""

    def fixture(self, mode: str) -> RegistrationFixture:
        """Create one canonical temporary current-route export."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        return RegistrationFixture(root, mode)

    def test_short_and_long_success_record_bound_sidecar(self) -> None:
        """A successful child must return the exact export-side proof."""
        for mode in ('short', 'long'):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                with mock.patch('studio.native_visual_usage_registration.subprocess.run',
                                side_effect=fixture.successful_child):
                    result = register_completed_visual_usage(fixture.request, {'PATH': '/usr/bin'})
                self.assertEqual(result['registration']['path'],
                                 str(fixture.output / REGISTRATION_FILE))
                self.assertFalse(result['humanApprovalClaim'])

    def test_short_and_long_failure_preserve_recoverable_delivery(self) -> None:
        """Registration failure never mutates or removes final render evidence."""
        for mode in ('short', 'long'):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                failed = subprocess.CompletedProcess([], 1, b'', b'TEST registration failed')
                with mock.patch('studio.native_visual_usage_registration.subprocess.run',
                                return_value=failed), self.assertRaises(VisualUsageRegistrationError):
                    register_completed_visual_usage(fixture.request, {'PATH': '/usr/bin'})
                self.assertEqual(json.loads((fixture.output / 'delivery.json').read_text())['status'],
                                 fixture.status)
                self.assertFalse((fixture.output / REGISTRATION_FILE).exists())

    def test_short_and_long_recovery_is_idempotent(self) -> None:
        """The fallback command can bind a prior receipt without changing identity."""
        for mode in ('short', 'long'):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                with mock.patch('studio.native_visual_usage_registration.subprocess.run',
                                side_effect=fixture.successful_child):
                    first = register_completed_visual_usage(fixture.request, {'PATH': '/usr/bin'})
                    second = register_completed_visual_usage(fixture.request, {'PATH': '/usr/bin'})
                self.assertEqual(first['digest'], second['digest'])
                self.assertEqual(first['registration'], second['registration'])

    def test_short_and_long_pipeline_fail_closed_after_checked_delivery(self) -> None:
        """A missing usage receipt rejects workflow success but preserves render evidence."""
        for mode in ('short', 'long'):
            with self.subTest(mode=mode):
                root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
                output = root / mode
                output.mkdir()
                review = output / 'review.mp4'
                review.write_bytes(b'TEST preserved render bytes')
                request = {'output': str(output), 'project': str(root),
                    **({'adapter': 'native-long'} if mode == 'long' else {})}
                result = {'status': f'native-{mode}-checked-for-review',
                    'output': str(review), 'humanApproved': False}
                failure = VisualUsageRegistrationError('TEST receipt write failed')
                pipeline = NativeShortPipeline(request, {})
                with mock.patch('studio.native_short_pipeline.register_completed_visual_usage',
                                side_effect=failure), contextlib.redirect_stdout(io.StringIO()):
                    self.assertFalse(pipeline.complete(result, time.monotonic()))
                delivery = json.loads((output / 'delivery.json').read_text())
                self.assertEqual(delivery['status'], result['status'])
                self.assertEqual(review.read_bytes(), b'TEST preserved render bytes')

    def test_transitive_typescript_and_planner_tamper_fail_before_cli(self) -> None:
        """Every runtime used by registration must retain its export-time hash."""
        for relative in ('src/lib/server/auto-edit-pipeline-authority.ts',
                         'scripts/producer/planner/visual_plan_validation.py',
                         'scripts/producer/graphics/comp_capabilities.py'):
            with self.subTest(relative=relative):
                fixture = self.fixture('short')
                fixture.request['pins'][str(REPO / relative)] = '0' * 64
                write_json(fixture.output / 'export-request.json', fixture.request)
                with mock.patch('studio.native_visual_usage_registration.subprocess.run') as run, \
                        self.assertRaisesRegex(VisualUsageRegistrationError,
                                              'implementation changed'):
                    register_completed_visual_usage(fixture.request, {'PATH': '/usr/bin'})
                run.assert_not_called()

    def test_python_registration_closure_is_completely_pinned(self) -> None:
        """A new local planner import cannot silently escape export-time pins."""
        entries = [REPO / 'scripts/producer/studio/native_visual_usage_registration.py',
                   REPO / 'scripts/producer/planner/visual_plan_cli.py']
        expected = local_python_closure(entries)
        actual = {file.resolve() for file in usage_implementation_files()
                  if file.suffix == '.py'}
        self.assertEqual(actual, expected)

    def test_typescript_registration_bundle_is_completely_pinned(self) -> None:
        """The exact bundled TS/JSON closure must match the export-time pin set."""
        script = """const e=require('esbuild');
const r=e.buildSync({entryPoints:['scripts/producer/visual-plan-usage.ts'],
bundle:true,write:false,platform:'node',format:'esm',metafile:true,packages:'external'});
process.stdout.write(JSON.stringify(Object.keys(r.metafile.inputs)));"""
        result = subprocess.run(['node', '-e', script], cwd=REPO, check=True,
                                stdout=subprocess.PIPE, text=True)
        expected = {(REPO / item).resolve() for item in json.loads(result.stdout)}
        actual = {file.resolve() for file in usage_implementation_files()
                  if file.suffix in {'.ts', '.json'}}
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
