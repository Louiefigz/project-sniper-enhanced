"""F8 (build side): the Node floor is derived from both lockfiles with npm's own semver.

Run: .venv/bin/python -m unittest release.tests.test_node_floor
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from release.node_floor import node_requirements
from release.stage import StagingError

ROOT = Path(__file__).resolve().parents[2]


def _lock_root(base: Path, packages: dict[str, dict]) -> Path:
    """A release-source-shaped folder with two lockfiles and the real semver package."""
    root = base / "src"
    for name in ("package-lock.json", "templates/motion/package-lock.json"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(json.dumps({"lockfileVersion": 3, "packages": {"": {}, **packages}}))
    (root / "node_modules").mkdir()
    shutil.copytree(ROOT / "node_modules/semver", root / "node_modules/semver")
    return root


class BuildTimeFloor(unittest.TestCase):
    """release.node_floor over synthetic and real lockfiles."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-floor-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def test_real_lockfiles_need_at_least_22_12(self) -> None:
        result = node_requirements(ROOT)
        self.assertGreaterEqual(tuple(map(int, result["floor"].split("."))), (22, 12, 0))
        self.assertIn("templates/motion/package-lock.json:node_modules/puppeteer-core", result["set_by"])

    def test_floor_is_the_lowest_version_every_range_accepts(self) -> None:
        root = _lock_root(self.base, {
            "node_modules/a": {"engines": {"node": ">=18"}},
            "node_modules/b": {"engines": {"node": "^20.19.0 || ^22.13.0 || >=24"}},
            "node_modules/c": {"engines": {"node": ">=22.12.0"}},
            "node_modules/win-only": {"engines": {"node": "^20.9.0"}, "os": ["win32"], "cpu": ["ia32"]}})
        result = node_requirements(root)
        self.assertEqual(result["floor"], "22.13.0")
        self.assertEqual(result["unsupported_majors"], [23])

    def test_an_unevaluable_range_fails_the_build(self) -> None:
        root = _lock_root(self.base, {"node_modules/odd": {"engines": {"node": "node >= banana"}}})
        with self.assertRaises(StagingError):
            node_requirements(root)

    def test_ranges_no_node_22_satisfies_fail_the_build(self) -> None:
        root = _lock_root(self.base, {"node_modules/old": {"engines": {"node": "^18 || ^20"}}})
        with self.assertRaises(StagingError):
            node_requirements(root)


if __name__ == "__main__":
    unittest.main()
