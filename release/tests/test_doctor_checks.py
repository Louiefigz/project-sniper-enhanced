"""Doctor checks added in rc4: external tools (F3), provider settings (F1) and the real
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

    def test_missing_tesseract_and_ytdlp_fail_with_brew_commands(self) -> None:
        empty = self.base / "bin"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            doctor_setup.check_external_tools(self._record)
        by_name = {name: (state, detail) for state, name, detail in self.rows}
        self.assertEqual(by_name["tesseract"][0], "FAIL")
        self.assertIn("brew install tesseract", by_name["tesseract"][1])
        self.assertIn("reference study", by_name["tesseract"][1])
        self.assertEqual(by_name["yt-dlp"][0], "FAIL")
        self.assertIn("brew install yt-dlp", by_name["yt-dlp"][1])

    @unittest.skipUnless(shutil.which("tesseract") and shutil.which("yt-dlp"), "tools not on this Mac")
    def test_present_tools_pass(self) -> None:
        doctor_setup.check_external_tools(self._record)
        self.assertEqual({n: s for s, n, _ in self.rows}, {"whisper-cli": "PASS", "tesseract": "PASS", "yt-dlp": "PASS"})

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
