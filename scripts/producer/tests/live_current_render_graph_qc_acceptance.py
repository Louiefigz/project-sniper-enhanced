"""Opt-in actual assemble proof that graph ACTIVE cannot precede QC promotion."""
from __future__ import annotations

import json
import unittest

from current_render_graph_candidate import (
    activate_candidate,
    verify_candidate,
)
from current_render_graph_contract import file_hash
from current_render_oracle import prove
from live_current_render_graph_acceptance import (
    _LIVE,
    _active_graph,
    _active_receipt,
    _command,
    _forced,
    _manifest,
    _media,
    _plan,
    _project,
    _run,
    _workspace,
)


def _deferred(command: list[str]) -> list[str]:
    command.insert(command.index("--"), "--defer-active")
    return command


@unittest.skipUnless(_LIVE, "set RUN_LIVE_CURRENT_RENDER_GRAPH=1")
class LiveCurrentRenderGraphQcAcceptance(unittest.TestCase):
    def test_actual_candidate_stays_private_until_exact_activation(self) -> None:
        with _workspace("qc-gated-graph-candidate") as root:
            source = root / "source.mp4"
            _media(source)
            (root / "project.json").write_text(json.dumps({
                "origin": "fixture", "history": [],
                "resolvedIntent": {
                    "mode": "longform", "scope": "trim", "lanes": {},
                },
            }))
            manifest = _manifest(root / "source-authority", source)
            project = root / "incremental"
            plan, final = _project(project, source, "BEFORE")
            _run(_command(project, plan, manifest, final))
            prior = _active_graph(project)

            plan.write_text(json.dumps(_plan("AFTER")))
            candidate = project / ".sniper-qc" / "round-2" / "final.mp4"
            candidate.parent.mkdir(parents=True)
            staged = _run(_deferred(_command(
                project, plan, manifest, candidate)))
            self.assertIn("render_graph_candidate_staged", staged)
            self.assertEqual(_active_graph(project), prior)
            expected = file_hash(candidate)
            verify_candidate(project, candidate, expected)

            candidate.replace(final)
            activate_candidate(project, candidate, final, expected)
            receipt = _active_receipt(project)
            self.assertEqual(
                set(receipt["dirtyNodeIds"]),
                {"node-scene-0000", "node-composite", "node-final"},
            )
            self.assertEqual(
                next(row for row in receipt["artifacts"]
                     if row["nodeId"] == "node-final")["path"],
                str(final.resolve()),
            )

            control = root / "forced"
            control_plan, control_final = _project(
                control, source, "AFTER")
            _run(_forced(_command(
                control, control_plan, manifest, control_final)))
            oracle = prove(
                final, control_final, root / "qc-gated-oracle.json")
            self.assertTrue(oracle["passed"])
            self.assertTrue(oracle["decodedAudioMatch"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
