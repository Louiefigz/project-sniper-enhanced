"""F8 (install side): one validated Node, recorded by its real path, refused when too old.

Run: .venv/bin/python -m unittest release.tests.test_node_selection
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from release.tests import _fixture as fx

sys.path.insert(0, str(fx.INSTALL_SRC / "lib"))
import doctor_setup  # noqa: E402

REAL_NODE = shutil.which("node", path="/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", ""))


def _stub_node(folder: Path, version: str) -> Path:
    """A 'node' that reports a version and nothing else (a too-old install)."""
    folder.mkdir(parents=True, exist_ok=True)
    stub = folder / "node"
    stub.write_text(f"#!/bin/bash\necho v{version}\n")
    stub.chmod(0o755)
    return stub


class InstallerAndDoctorNode(unittest.TestCase):
    """The installer's select_node and the doctor's node check, with real and stub Nodes."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-node-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)

    def _select(self, path_prefix: str) -> subprocess.CompletedProcess:
        env = {**fx.base_env(self.pkg), "PATH": f"{path_prefix}:{fx.FINDER_PATH}"}
        return fx.bash(self.pkg, '. "$FIXTURE_PKG/install/lib/steps.sh"; select_node && printf "NODE=%s\\n" "$NODE_BIN"', env)

    def test_installer_refuses_a_node_that_reports_22_0_0(self) -> None:
        stub = _stub_node(self.base / "oldnode", "22.0.0").parent
        done = self._select(str(stub))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("older than 22.13.0", done.stdout + done.stderr)

    @unittest.skipUnless(REAL_NODE, "no real node on this machine")
    def test_installer_records_the_real_binary_of_a_node_in_a_nonstandard_folder(self) -> None:
        custom = self.base / "tools/nvm-like/versions/node/bin"
        custom.mkdir(parents=True)
        (custom / "node").symlink_to(REAL_NODE)
        done = self._select(str(custom))
        self.assertEqual(done.returncode, 0, done.stderr)
        recorded = done.stdout.strip().splitlines()[-1].removeprefix("NODE=")
        self.assertEqual(recorded, os.path.realpath(REAL_NODE))

    def test_doctor_fails_a_node_that_reports_22_0_0(self) -> None:
        stub = _stub_node(self.base / "oldnode", "22.0.0")
        rows: list[tuple[str, str, str]] = []
        with mock.patch.dict(os.environ, {"SNIPER_NODE_PATH": str(stub), "PATH": str(stub.parent)}), \
                mock.patch.object(doctor_setup, "PKG_ROOT", self.pkg):
            doctor_setup.check_node(lambda *row: rows.append(row))
        self.assertEqual(rows[0][0], "FAIL")
        self.assertIn("older than 22.13.0", rows[0][2])

    @unittest.skipUnless(REAL_NODE, "no real node on this machine")
    def test_doctor_fails_when_path_finds_a_different_node(self) -> None:
        other = _stub_node(self.base / "other", "24.0.0")
        rows: list[tuple[str, str, str]] = []
        with mock.patch.dict(os.environ, {"SNIPER_NODE_PATH": os.path.realpath(REAL_NODE),
                                          "PATH": str(other.parent)}), \
                mock.patch.object(doctor_setup, "PKG_ROOT", self.pkg):
            doctor_setup.check_node(lambda *row: rows.append(row))
        self.assertEqual(rows[0][0], "FAIL")
        self.assertIn("different Node", rows[0][2])

    def test_version_comparison_is_numeric_not_textual(self) -> None:
        done = fx.bash(self.pkg, 'for p in "22.13.0 22.13.0" "22.100.0 22.13.0" "24.0.0 22.13.0" "22.12.9 22.13.0" '
                                 '"9.0.0 22.13.0"; do version_ge $p && echo "ge $p" || echo "lt $p"; done')
        self.assertEqual(done.stdout.splitlines(), ["ge 22.13.0 22.13.0", "ge 22.100.0 22.13.0",
                                                    "ge 24.0.0 22.13.0", "lt 22.12.9 22.13.0", "lt 9.0.0 22.13.0"])


if __name__ == "__main__":
    unittest.main()
