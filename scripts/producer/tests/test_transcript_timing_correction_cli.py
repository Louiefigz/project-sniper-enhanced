"""Actual Python CLI and competing TEST records; no decoder or model invocation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from _timing_correction_fixture import TimingCorrectionFixture

SCRIPT = Path(__file__).resolve().parents[1] / "transcript_timing_correction.py"


class TimingCorrectionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)
        self.proposal_path = self.fixture.root / "TEST-proposal.json"
        self.proposal_path.write_text(json.dumps(self.fixture.proposed))
        self.environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        self.environment.pop("PYTHONPATH", None)

    def command(self, verb: str, submitted: Path | None = None) -> list[str]:
        """Exercise the standalone script without PYTHONPATH assistance."""
        result = [sys.executable, str(SCRIPT), verb, str(self.fixture.plan),
                  str(self.fixture.manifest), str(self.fixture.transcript), str(self.proposal_path)]
        return result + ([str(submitted)] if submitted else [])

    def call(self, verb: str, submitted: Path | None = None) -> dict:
        """Run only this bounded tiny metadata transaction."""
        result = subprocess.run(self.command(verb, submitted), env=self.environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_standalone_prepare_record_status_and_replay_preserve_originals(self) -> None:
        before = self.fixture.parent_inventory()
        prepared = self.call("prepare")
        sent = self.fixture.root / "TEST-simulated-human.json"
        sent.write_text(json.dumps(self.fixture.submission(prepared)))
        recorded = self.call("record", sent)
        self.assertEqual(self.call("status")["revision"], recorded["revision"])
        self.assertTrue(self.call("record", sent)["replayed"])
        self.assertFalse(recorded["selected"])
        self.assertEqual(before, self.fixture.parent_inventory())

    def test_two_actual_record_processes_have_one_winner_and_no_failure_poison(self) -> None:
        prepared = self.call("prepare")
        children = []
        try:
            for index in range(2):
                sent = self.fixture.root / f"TEST-simulated-human-{index}.json"
                sent.write_text(json.dumps(self.fixture.submission(prepared)))
                children.append(subprocess.Popen(self.command("record", sent), env=self.environment,
                                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            results = [child.communicate(timeout=10) for child in children]
            self.assertEqual(sorted(child.returncode for child in children), [0, 1], results)
            self.assertEqual(self.call("status")["state"], "committed")
            self.assertFalse((self.fixture.correction_root / "failure.json").exists())
        finally:
            for child in children:
                self.stop_child(child)

    @staticmethod
    def stop_child(child: subprocess.Popen) -> None:
        """Only terminate an exact owned TEST child if a test assertion fails."""
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()

    def test_record_requires_submission_and_prepare_rejects_it(self) -> None:
        commands = [self.command("record"), self.command("prepare", self.proposal_path)]
        for command in commands:
            result = subprocess.run(command, env=self.environment, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)
        self.assertFalse(self.fixture.correction_root.exists())


if __name__ == "__main__":
    unittest.main()
