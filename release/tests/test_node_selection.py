"""The installer and the doctor use Sniper's own Node, whatever Node this Mac has on PATH.

Run: .venv/bin/python -m unittest release.tests.test_node_selection
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from release.tests import _fixture as fx

sys.path.insert(0, str(fx.INSTALL_SRC / "lib"))
import doctor_setup  # noqa: E402


def _stub_node(folder: Path, version: str) -> Path:
    """A 'node' that reports a version: a regular file, never a link to a real Node."""
    folder.mkdir(parents=True, exist_ok=True)
    stub = folder / "node"
    stub.write_text(f"#!/bin/bash\necho v{version}\n")
    stub.chmod(0o755)
    return stub


class InstallerAndDoctorNode(unittest.TestCase):
    """use_runtime_tools and the doctor's node check, with stand-in Nodes."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-node-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        self.prefix = fx.runtime_prefix(self.base / "home")

    def _use(self, path_prefix: str) -> tuple[int, str]:
        env = {**fx.base_env(self.pkg), "PATH": f"{path_prefix}:{fx.FINDER_PATH}"}
        done = fx.bash(self.pkg, '. "$FIXTURE_PKG/install/lib/steps.sh"; deps_paths; use_runtime_tools '
                                 '&& printf "NODE=%s\\nNPM=%s\\nPY=%s\\n" "$NODE_BIN" "$NPM_BIN" "$PYTHON_BIN"', env)
        return done.returncode, done.stdout + done.stderr

    def test_installer_uses_sniper_node_even_with_node_23_first_on_path(self) -> None:
        other = _stub_node(self.base / "homebrew-like/bin", "23.10.0").parent
        code, output = self._use(str(other))
        self.assertEqual(code, 0, output)
        self.assertIn(f"NODE={self.prefix}/bin/node", output)
        self.assertIn(f"NPM={self.prefix}/bin/npm", output)
        self.assertIn(f"PY={self.prefix}/bin/python3", output)
        self.assertIn("Node 24.21.0", output)
        self.assertNotIn("23.10.0", output)

    def test_installer_refuses_a_private_node_older_than_the_floor(self) -> None:
        _stub_node(self.prefix / "bin", "22.0.0")
        code, output = self._use("")
        self.assertNotEqual(code, 0)
        self.assertIn("Sniper's own Node cannot be used", output)
        self.assertIn("older than 22.13.0", output)

    def _doctor(self, pinned: Path, path: Path, prefix: Path | None = None) -> tuple[str, str, str]:
        rows: list[tuple[str, str, str]] = []
        with mock.patch.dict(os.environ, {"SNIPER_NODE_PATH": str(pinned), "PATH": str(path),
                                          "SNIPER_DEPS_PREFIX": str(prefix or self.prefix)}), \
                mock.patch.object(doctor_setup, "PKG_ROOT", self.pkg):
            doctor_setup.check_node(lambda *row: rows.append(row))
        return rows[0]

    def test_doctor_passes_sniper_node(self) -> None:
        node = self.prefix / "bin/node"
        state, _, detail = self._doctor(node, node.parent)
        self.assertEqual(state, "PASS", detail)
        self.assertIn("v24.21.0", detail)

    def test_doctor_fails_a_node_outside_sniper_tools(self) -> None:
        stub = _stub_node(self.base / "elsewhere", "24.1.0")
        state, _, detail = self._doctor(stub, stub.parent)
        self.assertEqual(state, "FAIL")
        self.assertIn("is not Sniper's own Node", detail)

    def test_doctor_fails_a_node_that_reports_22_0_0(self) -> None:
        stub = _stub_node(self.prefix / "bin", "22.0.0")
        state, _, detail = self._doctor(stub, stub.parent)
        self.assertEqual(state, "FAIL")
        self.assertIn("older than 22.13.0", detail)

    def test_doctor_fails_when_path_finds_a_different_node(self) -> None:
        other = _stub_node(self.base / "other", "24.0.0")
        state, _, detail = self._doctor(self.prefix / "bin/node", other.parent)
        self.assertEqual(state, "FAIL")
        self.assertIn("different Node", detail)

    def test_version_comparison_is_numeric_not_textual(self) -> None:
        done = fx.bash(self.pkg, 'for p in "22.13.0 22.13.0" "22.100.0 22.13.0" "24.0.0 22.13.0" "22.12.9 22.13.0" '
                                 '"9.0.0 22.13.0"; do version_ge $p && echo "ge $p" || echo "lt $p"; done')
        self.assertEqual(done.stdout.splitlines(), ["ge 22.13.0 22.13.0", "ge 22.100.0 22.13.0",
                                                    "ge 24.0.0 22.13.0", "lt 22.12.9 22.13.0", "lt 9.0.0 22.13.0"])


if __name__ == "__main__":
    unittest.main()
