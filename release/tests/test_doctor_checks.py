"""Doctor checks added in rc4: Sniper's own tools, provider settings (F1) and the real
media-admission sample interface (another workstream supplies the self-test).

Run: .venv/bin/python -m unittest release.tests.test_doctor_checks
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
import install_tools  # noqa: E402

SELFTESTS = {
    "ok": 'import json; print(json.dumps({"ok": True, "detail": "sample admitted"}))',
    "not-ok": 'import json, sys; print(json.dumps({"ok": False, "detail": "sandbox refused"})); sys.exit(1)',
    "ok-json-but-nonzero": 'import json, sys; print(json.dumps({"ok": True, "detail": "x"})); sys.exit(3)',
    "garbage": 'print("admitted, probably")',
    "slow": 'import time; time.sleep(30)',
}


class DoctorChecks(unittest.TestCase):
    """Each check records rows through the same callback the doctor uses."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-doctor-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.rows: list[tuple[str, str, str]] = []

    def _record(self, *row: str) -> None:
        self.rows.append(row)

    def _installed(self, record: bool = True) -> Path:
        """Stand-in tools, recorded the way the installer records them."""
        prefix = fx.make_runtime(self.base / "home")
        if record:
            install_tools.tree_record(prefix, prefix.parent / f"{prefix.name}.tree.json", doctor_setup.RUNTIME_EXCLUDES)
        return prefix

    def _tools(self, prefix: Path, path_first: Path | None = None) -> dict[str, tuple[str, str]]:
        """Run check_runtime_tools; name -> (state, detail)."""
        path = f"{path_first}:{prefix / 'bin'}" if path_first else str(prefix / "bin")
        with mock.patch.dict(os.environ, {"PATH": path, "SNIPER_DEPS_PREFIX": str(prefix)}):
            doctor_setup.check_runtime_tools(self._record)
        return {name: (state, detail) for state, name, detail in self.rows}

    def test_intact_tools_found_first_pass(self) -> None:
        rows = self._tools(self._installed())
        self.assertEqual({n: s for n, (s, _) in rows.items()},
                         {n: "PASS" for n in ("Sniper's own tools", "ffmpeg", "ffprobe", "whisper-cli",
                                              "tesseract", "yt-dlp", "node", "python3", "git")})
        self.assertIn("files verified", rows["Sniper's own tools"][1])

    def test_a_changed_tool_file_fails_and_names_the_fix(self) -> None:
        prefix = self._installed()
        (prefix / "bin/git").write_text("#!/bin/bash\necho tampered\n")
        rows = self._tools(prefix)
        self.assertEqual(rows["Sniper's own tools"][0], "FAIL")
        self.assertIn("1 file(s) differ", rows["Sniper's own tools"][1])
        self.assertIn("install/install.command", rows["Sniper's own tools"][1])

    def test_what_the_tools_write_themselves_is_not_a_change(self) -> None:
        prefix = self._installed()
        for rel in ("var/cache/fontconfig/x.cache", "lib/python3/__pycache__/m.pyc", ".sniper-users/abc"):
            (prefix / rel).parent.mkdir(parents=True, exist_ok=True)
            (prefix / rel).write_text("written at run time")
        self.assertEqual(self._tools(prefix)["Sniper's own tools"][0], "PASS")

    def test_a_tool_found_first_elsewhere_fails(self) -> None:
        other = self.base / "homebrew-like/bin"   # a stand-in file first on PATH, never a real tool
        other.mkdir(parents=True)
        (other / "ffmpeg").write_text("#!/bin/bash\necho ffmpeg version 7\n")
        (other / "ffmpeg").chmod(0o755)
        rows = self._tools(self._installed(), path_first=other)
        self.assertEqual(rows["ffmpeg"][0], "FAIL")
        self.assertIn(f"PATH finds {other / 'ffmpeg'}, not Sniper's own", rows["ffmpeg"][1])
        self.assertEqual(rows["ffprobe"][0], "PASS")

    def test_no_record_means_not_installed(self) -> None:
        rows = self._tools(self._installed(record=False))
        self.assertEqual(rows["Sniper's own tools"][0], "FAIL")
        self.assertIn("not installed", rows["Sniper's own tools"][1])

    def test_provider_settings_must_agree(self) -> None:
        cases = {("codex", "codex"): "PASS", ("claude", "legacy"): "PASS",
                 ("claude", "codex"): "FAIL", ("codex", "legacy"): "FAIL", ("", "codex"): "FAIL"}
        for (provider, brain), want in cases.items():
            with self.subTest(provider=provider, brain=brain):
                self.rows.clear()
                env = {"SNIPER_PROVIDER": provider, "SNIPER_BRAIN_PROVIDER": brain, "SNIPER_CODEX_MODEL": "gpt-5.6-sol",
                       "SNIPER_CLAUDE_MODEL": "opus", "SNIPER_CODEX_REASONING": "xhigh"}
                with mock.patch.dict(os.environ, env):
                    doctor_setup.check_provider_settings(self._record)
                self.assertEqual(self.rows[0][0], want)

    def _admission(self, script: str | None, timeout: int = 60) -> tuple[str, str]:
        app = self.base / "app"
        (app / ".venv/bin").mkdir(parents=True, exist_ok=True)
        python = app / ".venv/bin/python3"
        if not python.exists():  # a regular wrapper FILE, never a link to the real interpreter
            python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            python.chmod(0o755)
        selftest = app / "scripts/producer/headless/native_admission_selftest.py"
        if script is not None:
            selftest.parent.mkdir(parents=True, exist_ok=True)
            selftest.write_text(script)
        self.rows.clear()
        with mock.patch.object(doctor_setup, "APP", app), mock.patch.object(doctor_setup, "PKG_ROOT", self.base), \
                mock.patch.object(doctor_setup, "ADMISSION_SELFTEST", selftest), \
                mock.patch.object(doctor_setup, "ADMISSION_TIMEOUT_S", timeout):
            doctor_setup.check_media_admission(self._record)
        state, name, detail = self.rows[0]
        self.assertEqual(name, "media admission (real sample)")
        return state, detail

    def test_media_admission_fails_when_the_selftest_is_not_shipped(self) -> None:
        state, detail = self._admission(None)
        self.assertEqual(state, "FAIL")
        self.assertIn("native_admission_selftest.py", detail)

    def test_media_admission_passes_only_on_exit_0_and_ok_true(self) -> None:
        results = {name: self._admission(code, timeout=3)[0] for name, code in SELFTESTS.items()}
        self.assertEqual(results, {"ok": "PASS", "not-ok": "FAIL", "ok-json-but-nonzero": "FAIL",
                                   "garbage": "FAIL", "slow": "FAIL"})

    def test_no_docker_prerequisite_check_remains(self) -> None:
        doctor = (fx.INSTALL_SRC / "sniper_doctor.py").read_text() + (fx.INSTALL_SRC / "lib/doctor_setup.py").read_text()
        self.assertNotIn("media admission sandbox", doctor)
        self.assertNotIn("attest_image", doctor)
        self.assertNotIn("always fails", (fx.INSTALL_SRC / "install.command").read_text())


if __name__ == "__main__":
    unittest.main()
