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


def _stub_node(folder: Path, version: str) -> Path:
    """A 'node' that reports a version and, for `-p ...execPath`, its own real path.

    A regular file (never a link to a real Node), so the tests do not depend on which
    Node this Mac happens to run.
    """
    folder.mkdir(parents=True, exist_ok=True)
    stub = folder / "node"
    stub.write_text(f'#!/bin/bash\ncase "$1" in\n  -p) /usr/bin/readlink -f "$0" ;;\n  *) echo v{version} ;;\nesac\n')
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

    def test_installer_records_the_real_binary_of_a_node_in_a_nonstandard_folder(self) -> None:
        real = _stub_node(self.base / "tools/nvm-like/versions/node/v24.1.0/bin", "24.1.0")
        custom = self.base / "tools/fnm-like/multishell/bin"
        custom.mkdir(parents=True)
        (custom / "node").symlink_to(real)  # the per-shell link is what is tested; it points at a stub
        done = self._select(str(custom))
        self.assertEqual(done.returncode, 0, done.stderr)
        recorded = done.stdout.strip().splitlines()[-1].removeprefix("NODE=")
        self.assertEqual(recorded, os.path.realpath(real))

    def test_installer_refuses_node_23_with_the_exact_fix(self) -> None:
        stub = _stub_node(self.base / "node23", "23.10.0")
        done = self._select(str(stub.parent))
        said = " ".join((done.stdout + done.stderr).split())
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"Node 23.10.0 ({os.path.realpath(stub)}) is not supported", said)
        self.assertIn("Install Node 24 (LTS) from https://nodejs.org", said)
        self.assertIn("run 'brew upgrade node' instead", said)  # keg-only node@24 would not be on PATH

    def test_doctor_fails_node_23(self) -> None:
        stub = _stub_node(self.base / "node23", "23.10.0")
        rows: list[tuple[str, str, str]] = []
        with mock.patch.dict(os.environ, {"SNIPER_NODE_PATH": str(stub), "PATH": str(stub.parent)}), \
                mock.patch.object(doctor_setup, "PKG_ROOT", self.pkg):
            doctor_setup.check_node(lambda *row: rows.append(row))
        self.assertEqual(rows[0][0], "FAIL")
        self.assertIn(f"v23.10.0 at {stub} is not supported", rows[0][2])
        self.assertIn("brew upgrade node", rows[0][2])

    def test_doctor_fails_a_node_that_reports_22_0_0(self) -> None:
        stub = _stub_node(self.base / "oldnode", "22.0.0")
        rows: list[tuple[str, str, str]] = []
        with mock.patch.dict(os.environ, {"SNIPER_NODE_PATH": str(stub), "PATH": str(stub.parent)}), \
                mock.patch.object(doctor_setup, "PKG_ROOT", self.pkg):
            doctor_setup.check_node(lambda *row: rows.append(row))
        self.assertEqual(rows[0][0], "FAIL")
        self.assertIn("older than 22.13.0", rows[0][2])

    def test_doctor_fails_when_path_finds_a_different_node(self) -> None:
        pinned = _stub_node(self.base / "pinned", "24.1.0")
        other = _stub_node(self.base / "other", "24.0.0")
        rows: list[tuple[str, str, str]] = []
        with mock.patch.dict(os.environ, {"SNIPER_NODE_PATH": str(pinned),
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
