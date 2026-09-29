"""The real TypeScript submission accepts a Python-resolved scoped packet with shared evidence and keeps refusing
authors, untyped scene evidence bases and stale evidence.

Fixtures are TEST-labelled synthetic productions; nothing here is a real observation or review.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native_work_lease
from studio import native_budget_store
from test_role_packet_evidence import REPO, EvidenceFixture

TSX = REPO / "node_modules" / ".bin" / "tsx"


@unittest.skipUnless(shutil.which("node") and TSX.exists(), "the typed submission needs node and the repository tsx")
class SubmissionContractTests(EvidenceFixture):
    """The real TypeScript submission reads the scoped packet and keeps refusing authors and stale inputs."""

    def submit(self, published: dict) -> subprocess.CompletedProcess:
        """Run the packet's own submit-prebuild command; its engine given check reads this test's private roots
        (TEST harness _isolated_review.ts), never the user's authority."""
        roots = (str(native_budget_store.default_root()), str(native_work_lease.state_root()))
        return subprocess.run(["node", "--import", "tsx", str(Path(__file__).resolve().parent / "_isolated_review.ts"),
                               sys.executable, *roots, "review", "submit-prebuild", published["packet"],
                               published["observations"], published["record"]],
                              cwd=REPO, capture_output=True, text=True, timeout=180, check=False)

    def observe(self, published: dict, session: str, basis: str = "inspected") -> None:
        """Complete the observations draft with TEST judgments for a declared reviewer session."""
        path = Path(published["observations"])
        draft = json.loads(path.read_text())
        draft["reviewer"] = {"identity": "TEST critic", "sessionId": session, "plannerSessionId": "TEST-author",
                             "independent": True}
        draft["coverage"] = {key: f"TEST {key} in the synthetic fixture" for key in draft["coverage"]}
        draft["scenes"] = [{**row, "note": f"TEST scene {row['index']}", "evidenceBasis": basis} for row in draft["scenes"]]
        draft.update({"verdict": "revise", "summary": "TEST synthetic review", "limitations": ["TEST no listening"],
                      "materialIssues": [{"code": "TEST_MATERIAL", "severity": "major", "lane": "review",
                                          "message": "TEST issue", "evidence": ["TEST fixture"],
                                          "requiredAction": "TEST repair"}]})
        path.write_text(json.dumps(draft))

    def test_author_refused_fresh_critic_accepted_stale_evidence_refused(self) -> None:
        """One packet shape, four outcomes from the submission contract, including the typed scene basis."""
        record = self.sealed()
        plan = self.evidence_plan()
        published = self.packet(record, plan, author_session="TEST-coauthor")["published"]
        self.observe(published, "TEST-coauthor")
        refused = self.submit(published)
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("is a recorded author of this work", refused.stderr)
        self.observe(published, "TEST-fresh-critic", basis="guessed")
        self.assertIn("evidenceBasis is required with shared evidence bound: inspected or shared-evidence-only",
                      self.submit(published).stderr)
        self.observe(published, "TEST-fresh-critic", basis="shared-evidence-only")
        accepted = self.submit(published)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout)["status"], "recorded-plan-review-requires-revision")
        later = self.packet(record, plan)["published"]
        self.observe(later, "TEST-fresh-critic")
        self.selections.write_text('{"TEST": "changed after the packet"}')
        stale = self.submit(later)
        self.assertEqual(stale.returncode, 1, stale.stdout)
        self.assertIn("shared-evidence:selections", stale.stderr)


if __name__ == "__main__":
    unittest.main()
