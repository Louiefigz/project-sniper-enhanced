"""P2-03 runtime reveal probe as an early check (M-068): the plan's five tests plus the wiring, all synthetic.

The TS writer, the managed runtime, the owned inspection and the Node probe are stubbed at their seams: nothing here
starts a child process, a browser, a NativeRun or the pool, and nothing reads footage (G17). The runs that need
them are listed in the lane hand-over and run at M-068's integration.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio import native_reveal_probe as probe
from studio.native_reveal_probe import RevealProbeOptions, reveal_check, reveal_defects

FILE = 'compositions/numbers-q1.html'
MOUNTS = [{'id': 'sn-numbers-q1', 'file': FILE, 'first': 745, 'endExclusive': 1087}]
FLASH = {'condition': 'first-frame-flash', 'mount': 'sn-numbers-q1', 'element': 'hf-panel', 'frame': 745,
         'localFrame': 0, 'order': 'forward', 'opacity': [1, 0]}
LINT = {'check': 'staticPreflight', 'severity': 'warning', 'code': probe.LINT_HINT, 'file': FILE,
        'message': 'TEST initial hide set inside the paused timeline'}
TOOLS = {'node': '/TEST/node'}


def result(findings: list[dict]) -> dict:
    """A probe result as ``native_reveal_probe.mjs`` writes it (series omitted; the check never reads it)."""
    return {'schemaVersion': 1, 'scope': 'native-reveal-probe',
            'status': 'premature-reveal-found' if findings else 'reveal-probe-pass',
            'runtimeLibrarySha256': 'a' * 64, 'compiledSha256': 'b' * 64, 'series': [], 'findings': findings,
            'visibleAtMount': [{'mount': 'sn-numbers-q1', 'frame': 745, 'elements': [],
                                'screenshot': {'file': 'mount-first-0.jpg', 'sha256': 'c' * 64}}]}


class RevealCheckTests(unittest.TestCase):
    """``reveal_check`` and ``reveal_defects`` with every child process and owner stubbed."""

    def setUp(self) -> None:
        """A built-project folder whose plan mounts one catalog file, and a new output path."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.write_plan([{'file': FILE}])
        self.options = RevealProbeOptions(self.project, self.base / 'reveal', (LINT,))
        self.calls: list[str] = []

    def write_plan(self, catalog_files: list[dict]) -> None:
        """The only plan field the check reads before probing."""
        (self.project / 'SHORT-PROJECT.json').write_text(json.dumps({'catalogFiles': catalog_files}))

    def fake_writer(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        """Stand-in for ``native-short.ts reveal-probe-project``: writes only the manifest the check reads."""
        self.calls.append('writer')
        self.assertEqual(command[1:5], ['--import', 'tsx', str(probe.REPO / 'scripts/producer/native-short.ts'),
                                        'reveal-probe-project'])
        self.assertEqual((command[5], kwargs['cwd']), (str(self.project), probe.REPO))
        Path(command[6]).mkdir()
        (Path(command[6]) / 'REVEAL-PROBE.json').write_text(json.dumps({'mounts': MOUNTS}))
        return subprocess.CompletedProcess(command, 0, '{}', '')

    def fake_inspection(self, worker: Path, root: Path, request: dict) -> dict:
        """Stand-in for ``run_inspection``: the owned worker, the probe folder and the probe project."""
        self.calls.append('inspection')
        self.assertEqual((worker, root), (probe.HERE, self.options.output / 'probe'))
        self.assertEqual(request, {'project': str(self.options.output / 'project'), 'runtime': '/TEST/runtime'})
        return {'path': str(root / 'result.json'), 'sha256': 'd' * 64, 'owner': 'TEST', 'ownerSha256': 'e' * 64}

    def check(self, owned: dict | Exception) -> dict:
        """Run ``reveal_check`` with the writer, runtime and inspection stubbed; ``owned`` is the read result."""
        read = {'side_effect': owned} if isinstance(owned, Exception) else {'return_value': owned}
        with patch('studio.native_run_config.local_environment', return_value=(TOOLS, {'PATH': '/TEST'})), \
                patch('studio.native_runtime.install_runtime', return_value=Path('/TEST/runtime')), \
                patch.object(probe.subprocess, 'run', side_effect=self.fake_writer), \
                patch('studio.owned_inspection.run_inspection', side_effect=self.fake_inspection), \
                patch('studio.owned_inspection.read_inspection', **read) as reader:
            value = reveal_check(self.options)
        if not isinstance(owned, Exception):
            self.assertEqual(reader.call_args.kwargs, {'require_owner_digest': True})
        return value

    def test_not_applicable_without_catalog_mounts(self) -> None:
        """E-R7: no catalog file means nothing to seek; nothing runs and the early report is not blocked."""
        self.write_plan([])
        guard = AssertionError('the probe ran without catalog mounts')
        with patch.object(probe.subprocess, 'run', side_effect=guard), \
                patch('studio.owned_inspection.run_inspection', side_effect=guard):
            value = reveal_check(self.options)
        self.assertEqual(value, {'status': 'not-applicable', 'reason': 'no catalog mounts'})
        self.assertEqual(reveal_defects(value), [])
        self.assertFalse(self.options.output.exists())

    def test_findings_become_blocking_defects(self) -> None:
        """A C1 finding in the owned result is one blocking ``premature-reveal`` defect with its location."""
        value = self.check(result([FLASH]))
        self.assertEqual(self.calls, ['writer', 'inspection'])
        self.assertEqual((value['status'], value['findings'], value['mounts']),
                         ('premature-reveal-found', [FLASH], [{'id': 'sn-numbers-q1', 'file': FILE}]))
        self.assertEqual((value['evidence'], value['resultSha256']), (str(self.options.output / 'probe/result.json'), 'd' * 64))
        [row] = reveal_defects(value)
        self.assertEqual({key: row[key] for key in ('check', 'severity', 'code', 'condition')},
                         {'check': 'revealProbe', 'severity': 'error', 'code': 'premature-reveal',
                          'condition': 'first-frame-flash'})
        self.assertEqual({key: row[key] for key in ('mount', 'element', 'frame', 'localFrame', 'order', 'opacity')},
                         {key: FLASH[key] for key in ('mount', 'element', 'frame', 'localFrame', 'order', 'opacity')})
        self.assertIn('frame 745', row['message'])
        passed = self.check_again(result([]))
        self.assertEqual((passed['status'], reveal_defects(passed)), ('reveal-probe-pass', []))

    def check_again(self, owned: dict) -> dict:
        """A second run into a fresh output folder."""
        self.options = RevealProbeOptions(self.project, self.base / 'reveal-2', (LINT,))
        return self.check(owned)

    def test_failed_probe_blocks_early_report(self) -> None:
        """E-R8: an owner failure, a refused writer or a result that contradicts itself is ``failed``, and blocks."""
        failed = self.check(RuntimeError('TEST inspection capacity refused'))
        self.assertEqual((failed['status'], failed['error']), ('failed', 'TEST inspection capacity refused'))
        self.assertEqual(reveal_defects(failed), [{'check': 'revealProbe', 'severity': 'error',
                                                   'code': 'reveal-probe-failed', 'message': failed['error']}])
        lying = self.check_again({**result([FLASH]), 'status': 'reveal-probe-pass'})
        self.assertEqual(lying['status'], 'failed')
        self.assertIn('status disagrees with its findings', lying['error'])
        refused = subprocess.CompletedProcess([], 1, '', 'TEST Catalog implementation is missing, changed or retired')
        self.options = RevealProbeOptions(self.project, self.base / 'reveal-3', ())
        with patch('studio.native_run_config.local_environment', return_value=(TOOLS, {})), \
                patch.object(probe.subprocess, 'run', return_value=refused), \
                patch('studio.owned_inspection.run_inspection', side_effect=AssertionError('probed a refused plan')):
            value = reveal_check(self.options)
        self.assertEqual(value['status'], 'failed')
        self.assertIn('Catalog implementation is missing', value['error'])
        self.assertEqual(reveal_defects(value)[0]['code'], 'reveal-probe-failed')

    def test_lint_warning_is_hint_not_verdict(self) -> None:
        """The lint warning rides on a finding for its file; without a finding it creates no defect."""
        self.assertEqual(reveal_defects(self.check(result([])) | {'lintWarnings': [LINT]}), [])
        found = self.check_again(result([FLASH]))
        self.assertEqual(found['lintWarnings'], [LINT])
        self.assertEqual(reveal_defects(found)[0]['lintHint'], LINT)
        elsewhere = {**LINT, 'file': 'compositions/title-q1.html'}
        self.assertIsNone(reveal_defects({**found, 'lintWarnings': [elsewhere]})[0]['lintHint'])
        other_code = {**LINT, 'code': 'gsap_css_transform_conflict'}
        self.assertIsNone(reveal_defects({**found, 'lintWarnings': [other_code]})[0]['lintHint'])


class WorkerTests(unittest.TestCase):
    """The owned worker: refused when detached; publishes exactly the Node probe's report when attached."""

    def setUp(self) -> None:
        """An inspection folder holding only its request."""
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.file = self.folder / 'request.json'
        self.file.write_text('{}\n')

    def test_worker_refuses_detached_request(self) -> None:
        """No live owner, or another owner's record: refused before the Node probe starts or anything is written."""
        detached = {key: value for key, value in os.environ.items() if not key.startswith('SNIPER_INSPECTION_')}
        other = {**detached, 'SNIPER_INSPECTION_REQUEST': str(self.file),
                 'SNIPER_INSPECTION_OWNER': str(self.folder / 'another.render.json')}
        for environment, message in ((detached, 'Inspection requires its live owner'), (other, 'Inspection owner changed')):
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(probe, 'run_bounded', side_effect=AssertionError('the probe started')), \
                    self.assertRaisesRegex(ValueError, message):
                probe.worker(self.file)
        self.assertEqual([path.name for path in self.folder.iterdir()], ['request.json'])

    def test_worker_publishes_the_probe_report(self) -> None:
        """Under a live owner the worker runs the admitted Node on the request and publishes the report as-is."""
        written = result([FLASH])

        def node(command: list[str], timeout: float) -> subprocess.CompletedProcess:
            """Stand-in for the bounded Node probe: writes the report where the CLI writes it."""
            self.assertEqual((command, timeout), (['/TEST/node', str(probe.PROBE), str(self.file)], probe.PROBE_SECONDS))
            (self.folder / 'reveal').mkdir()
            (self.folder / 'reveal/reveal-probe.json').write_text(json.dumps(written))
            return subprocess.CompletedProcess(command, 0, b'', b'')
        with patch('studio.owned_inspection.require_worker', return_value={'tools': TOOLS}) as owner, \
                patch.object(probe, 'run_bounded', side_effect=node):
            probe.worker(self.file)
        self.assertEqual(owner.call_count, 2)
        self.assertEqual(json.loads((self.folder / 'result.json').read_text()), written)

    def test_worker_refuses_a_failed_node_probe(self) -> None:
        """A non-zero Node exit is a refusal carrying its stderr; no result is published."""
        failed = subprocess.CompletedProcess([], 1, b'', b'TEST Reveal series malformed: rows disagree')
        with patch('studio.owned_inspection.require_worker', return_value={'tools': TOOLS}), \
                patch.object(probe, 'run_bounded', return_value=failed), \
                self.assertRaisesRegex(ValueError, 'Reveal series malformed'):
            probe.worker(self.file)
        self.assertFalse((self.folder / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
