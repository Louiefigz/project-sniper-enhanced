"""F2: every generated setting round-trips literally through the installer's own writer
and the launchers' own loader; control characters are refused with a clear message.

Run: .venv/bin/python -m unittest release.tests.test_installer_settings
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from release.tests import _fixture as fx

AWKWARD = {
    "space": "Client Videos/Season 2",
    "dollar": "Budget$97",
    "backtick": "a`touch PWNED`b",
    "command-substitution": "x$(touch PWNED)y",
    "single-quote": "it's mine",
    "double-quote": 'say "cut"',
    "backslash": "back\\slash\\n",
    "unicode": "Ünïcödé Vidéos 日本 🎬",
    "semicolon-hash": "a; rm -rf x # not a comment",
}
KEYS = ("SNIPER_WORKSPACE_ROOT", "SNIPER_NODE_PATH", "HYPERFRAMES_FFMPEG_PATH", "WHISPER_CPP_BIN",
        "SNIPER_PROVIDER", "SNIPER_BRAIN_PROVIDER", "SNIPER_CODEX_MODEL", "SNIPER_CLAUDE_MODEL")


class SettingsRoundTrip(unittest.TestCase):
    """Values go through write_settings (installer) and load_env (every launcher)."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-settings-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)

    def _loaded(self) -> dict[str, str]:
        """What a launcher sees: load_env in a fresh process, values printed as JSON."""
        keys = " ".join(KEYS)
        done = fx.bash(self.pkg, f'load_env || exit 1\nfor k in {keys}; do printf "%s\\0%s\\0" "$k" "${{!k}}"; done')
        self.assertEqual(done.returncode, 0, done.stderr)
        parts = done.stdout.split("\0")[:-1]
        return dict(zip(parts[::2], parts[1::2]))

    def test_workspace_and_executable_paths_round_trip_literally(self) -> None:
        for label, name in AWKWARD.items():
            with self.subTest(label):
                workspace = str(self.base / "videos" / name)
                tools = str(self.base / f"tools {name}")
                done = fx.write_settings(self.pkg, workspace, {
                    "NODE_BIN": f"{tools}/node", "TOOL_FFMPEG": f"{tools}/ffmpeg",
                    "TOOL_WHISPER_CLI": f"{tools}/whisper-cli"})
                self.assertEqual(done.returncode, 0, done.stderr)
                loaded = self._loaded()
                self.assertEqual(loaded["SNIPER_WORKSPACE_ROOT"], workspace)
                self.assertEqual(loaded["SNIPER_NODE_PATH"], f"{tools}/node")
                self.assertEqual(loaded["HYPERFRAMES_FFMPEG_PATH"], f"{tools}/ffmpeg")
                self.assertEqual(loaded["WHISPER_CPP_BIN"], f"{tools}/whisper-cli")
                self.assertTrue(Path(workspace).is_dir(), "the installer creates the literal folder")
        self.assertFalse(list(self.base.rglob("PWNED")), "a setting was executed as shell")

    def test_budget_dollar_97_is_not_budget7(self) -> None:
        workspace = str(self.base / "Budget$97")
        self.assertEqual(fx.write_settings(self.pkg, workspace).returncode, 0)
        self.assertEqual(self._loaded()["SNIPER_WORKSPACE_ROOT"], workspace)
        self.assertFalse((self.base / "Budget7").exists())

    def test_control_characters_are_refused_with_a_clear_message(self) -> None:
        for label, bad in {"newline": "two\nlines", "tab": "tab\there", "escape": "esc\x1b[0m"}.items():
            with self.subTest(label):
                done = fx.write_settings(self.pkg, str(self.base / bad))
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("control", done.stderr)
                self.assertIn("SNIPER_WORKSPACE_ROOT", done.stderr)
                self.assertFalse((self.pkg / "runtime/sniper.env").exists(), "a partial file was written")

    def test_rc3_format_file_is_still_read_for_the_upgrade(self) -> None:
        env = self.pkg / "runtime/sniper.env"
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text('PKG_ROOT="/old"\nSNIPER_PROVIDER="claude"\nSNIPER_WORKSPACE_ROOT="/Volumes/W/Budget$97"\n')
        done = fx.bash(self.pkg, 'printf "%s|%s" "$(settings_value SNIPER_PROVIDER)" "$(settings_value SNIPER_WORKSPACE_ROOT)"')
        self.assertEqual(done.stdout, "claude|/Volumes/W/Budget$97")

    def test_only_filtergraph_characters_are_refused_in_the_install_path(self) -> None:
        for char, refused in {"$": False, "`": False, '"': False, " ": False, "ü": False,
                              ",": True, "'": True, ":": True, "\\": True}.items():
            with self.subTest(repr(char)):
                pkg = fx.make_package(self.base, f"p{abs(hash(char))} x{char}y")
                done = fx.bash(pkg, "require_safe_install_path && echo accepted")
                self.assertEqual("accepted" not in done.stdout, refused, done.stderr)


if __name__ == "__main__":
    unittest.main()
