"""Reference matching CLI integration using real inert on-disk catalog evidence."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _reference_reuse_fixture import ReuseFixture
from graphics import reference_reuse_cli as cli


class ReferenceReuseCliTests(ReuseFixture):
    """Separate candidate preparation, planned readiness and failed checks."""

    def setUp(self) -> None:
        """Patch only catalog location; all mapping and exclusive I/O remain real."""
        super().setUp()
        self.enterContext(patch.object(cli, 'load_catalog', side_effect=self.catalog))
        self.mapping = self.root / 'map.json'

    def command(self, *argv: str) -> tuple[dict, int]:
        """Parse the production CLI shape and use its real execution handler."""
        return cli.execute(cli.parser().parse_args(list(argv)))

    def main_result(self, *argv: str) -> tuple[dict, int]:
        """Exercise the executable JSON/exit-code contract without a subprocess."""
        stream = io.StringIO()
        with patch.object(sys, 'argv', ['reference_reuse_cli.py', *argv]), \
                redirect_stdout(stream), self.assertRaises(SystemExit) as exit:
            cli.main()
        return json.loads(stream.getvalue()), exit.exception.code

    def test_prepare_writes_pending_map_and_requires_agent_inspection(self) -> None:
        """Candidate retrieval never silently chooses a route or approves execution."""
        request = self.request()['request']['path']
        report, code = self.command('prepare', request, '--output', str(self.mapping))
        record = json.loads(self.mapping.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'reference-reuse-draft')
        self.assertTrue(report['inspectionAndSelectionRequired'])
        self.assertFalse(report['renderApproved'])
        self.assertEqual(record['shots'][0]['decision'], {'route': 'pending'})
        self.assertEqual(record['shots'][0]['inspections'], [])

    def test_prepare_never_overwrites_existing_map(self) -> None:
        """Retries preserve the previous candidate/decision artifact exactly."""
        request = self.request()['request']['path']
        self.command('prepare', request, '--output', str(self.mapping))
        before = self.mapping.read_bytes()
        report, code = self.main_result('prepare', request, '--output', str(self.mapping))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(self.mapping.read_bytes(), before)

    def test_check_ready_emits_hashed_planning_receipt_only(self) -> None:
        """A completed map returns zero without claiming installed/rendered quality."""
        self.write_json(self.mapping, self.decided())
        output = self.root / 'checked.json'
        report, code = self.command('check', str(self.mapping), '--output', str(output))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text()), report)
        self.assertEqual(report['map'], self.pin(self.mapping))
        self.assertTrue(report['ready'])
        for field in ('renderApproved', 'qualityApproved', 'styleApproved', 'executionAdmitted'):
            self.assertFalse(report[field])

    def test_blocked_check_returns_one_and_retains_blocking_shots(self) -> None:
        """An unavailable adapter remains an explicit blocker in printed JSON."""
        record = self.decided()
        decision = record['shots'][0]['decision']
        decision['route'] = 'blocked'
        decision['execution']['status'] = 'unavailable'
        decision['prerequisites'] = [{'kind': 'adapter', 'detail': 'TEST unavailable runtime'}]
        self.write_json(self.mapping, record)
        report, code = self.main_result('check', str(self.mapping))
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'blocked-planning-only')
        self.assertEqual(report['blockedShots'], ['shot-1'])
        self.assertFalse(report['ready'])

    def test_pending_or_stale_check_fails_without_publishing_success(self) -> None:
        """A failed check preserves input evidence and leaves no output receipt."""
        self.write_json(self.mapping, self.prepared())
        before = self.mapping.read_bytes()
        output = self.root / 'unwritten.json'
        report, code = self.main_result('check', str(self.mapping), '--output', str(output))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('pending', report['error'])
        self.assertEqual(self.mapping.read_bytes(), before)
        self.assertFalse(output.exists())
        self.write_json(self.mapping, self.decided())
        self.plan.write_text('TEST changed shot plan')
        report, code = self.main_result('check', str(self.mapping), '--output', str(output))
        self.assertEqual(code, 2)
        self.assertIn('stale pinned file', report['error'])
        self.assertFalse(output.exists())

    def test_check_never_overwrites_prior_report_or_input_map(self) -> None:
        """Exclusive publication applies equally to checked reports and map paths."""
        self.write_json(self.mapping, self.decided())
        output = self.root / 'checked.json'
        self.command('check', str(self.mapping), '--output', str(output))
        for destination in (output, self.mapping):
            before = destination.read_bytes()
            report, code = self.main_result('check', str(self.mapping), '--output', str(destination))
            self.assertEqual(code, 2)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(destination.read_bytes(), before)

    def test_request_cannot_embed_self_binding_or_infer_matching_scope(self) -> None:
        """Only the explicitly requested external matching packet starts this work."""
        request = self.root / 'input.json'
        for body in ({**self.body, 'request': {}}, {**self.body, 'scope': 'inspiration'}):
            self.write_json(request, body)
            report, code = self.main_result('prepare', str(request), '--output', str(self.mapping))
            self.assertEqual(code, 2)
            self.assertEqual(report['status'], 'failed')
            self.assertFalse(self.mapping.exists())


if __name__ == '__main__':
    import unittest
    unittest.main()
