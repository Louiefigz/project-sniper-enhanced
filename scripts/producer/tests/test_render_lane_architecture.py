from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))


class RenderLaneArchitectureTests(unittest.TestCase):
    def test_new_root_has_no_gui_or_palmier_import(self) -> None:
        modules = set()
        names = (
            "container_io.py",
            "overlay_seal.py",
            "overlay_seal_store.py",
            "process_runner.py",
            "render_build.py",
            "render_lane.py",
            "render_lane_cache.py",
            "render_result.py",
            "render_runtime.py",
            "render_worker.py",
            "resource_ledger.py",
            "sealed_archive.py",
        )
        for name in names:
            tree = ast.parse((PRODUCER_DIR / "headless" / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module)
        forbidden = [
            name for name in modules if name.startswith(("palmier", "src.app"))
        ]
        self.assertEqual(forbidden, [])

    def test_legacy_render_entry_signature_is_unchanged(self) -> None:
        from graphics.graphics_render import render_entry

        parameters = inspect.signature(render_entry).parameters
        self.assertEqual(list(parameters), ["entry", "cache_dir"])
        self.assertIsNone(parameters["cache_dir"].default)
