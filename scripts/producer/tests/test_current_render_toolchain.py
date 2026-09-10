"""Current render-toolchain source-boundary tests."""
from __future__ import annotations

import unittest

from current_render_toolchain import current_toolchain_python_files
from render_effect_discovery import renderer_import_closure
from render_effect_registry import PROJECT_ROOT


class CurrentRenderToolchainTests(unittest.TestCase):
    def test_hashes_exact_renderer_closure_not_all_producer_code(self) -> None:
        observed = {
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in renderer_import_closure()
        }
        self.assertIn("scripts/producer/render.py", observed)
        self.assertIn("scripts/producer/motion/reframe_split.py", observed)
        self.assertIn("scripts/producer/audit/audit_render.py", observed)
        unrelated = {
            "scripts/producer/edit/cut_repair_candidate_qc_waveform.py",
            "scripts/producer/external_ingress_registry.py",
        }
        for relative in unrelated:
            self.assertTrue((PROJECT_ROOT / relative).is_file())
            self.assertNotIn(relative, observed)

    def test_surgical_stage_and_promotion_are_in_toolchain_closure(self) -> None:
        observed = {
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in current_toolchain_python_files()
        }
        required = {
            "scripts/producer/edit/cut_repair_surgical_terminal.py",
            "scripts/producer/edit/cut_repair_surgical_contract.py",
            "scripts/producer/edit/cut_repair_surgical_graph.py",
            "scripts/producer/current_render_graph_candidate.py",
            "scripts/producer/current_render_graph_candidate_cli.py",
            "scripts/producer/current_render_graph_source_gate.py",
        }
        self.assertTrue(required.issubset(observed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
