"""Build-side Windows target, source approval and payload checks."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from release import payload, runtime_tools

ROOT = Path(__file__).resolve().parents[2]
HEADLESS = ROOT / "scripts/producer/headless"


class WindowsRelease(unittest.TestCase):
    """The dynamic package carries a complete, internally consistent Windows lane."""

    def test_windows_runtime_lock_verifies(self) -> None:
        result = runtime_tools.check("win-64")
        self.assertEqual(result["runtime_min_windows"], "10.0.19045")
        self.assertIn("BtbN/FFmpeg-Builds", result["runtime_tools"]["ffmpeg"])

    def test_windows_jail_sources_match_the_approval(self) -> None:
        approval = json.loads((HEADLESS / "windows_media_runtime_approval.json").read_text())
        found = {name: hashlib.sha256((HEADLESS / name).read_bytes()).hexdigest()
                 for name in approval["approved"]}
        self.assertEqual(found, approval["approved"])
        jail = (HEADLESS / "windows_media_jail.cs").read_text()
        self.assertIn('CharSet=CharSet.Unicode, SetLastError=true', jail)
        self.assertIn('TokenIsAppContainer', jail)
        self.assertIn('CreateProcessAsUser', jail)
        self.assertIn('Job Object limits were not applied exactly', jail)
        self.assertIn('ProtectFile(args[1])', jail)

    def test_windows_jail_approval_bytes_keep_lf_on_windows(self) -> None:
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("scripts/producer/headless/windows_media_*.cs text eol=lf", attributes)
        self.assertIn("scripts/producer/studio/runtime/*.json text eol=lf", attributes)
        self.assertIn("scripts/producer/studio/runtime/*.mjs text eol=lf", attributes)

    def test_windows_buyer_entry_points_exist(self) -> None:
        required = ("sniper.cmd", "sniper.ps1", "install/install.ps1", "install/doctor.ps1",
                    "install/uninstall.ps1", "install/studio.cmd", "install/studio.ps1")
        self.assertFalse([name for name in required if not (payload.PAYLOAD / name).is_file()])

    def test_windows_powershell_sources_are_ascii(self) -> None:
        scripts = list((payload.PAYLOAD / "install").rglob("*.ps1"))
        non_ascii = [str(script.relative_to(payload.PAYLOAD)) for script in scripts
                     if not script.read_bytes().isascii()]
        self.assertEqual(non_ascii, [], "Windows PowerShell 5 misreads BOM-less UTF-8")
        reserved = [str(script.relative_to(payload.PAYLOAD)) for script in scripts
                    if "$home =" in script.read_text(encoding="ascii").lower()]
        self.assertEqual(reserved, [], "PowerShell's HOME variable is read-only")

    def test_windows_jail_uses_powershell_five_compiler_parameters(self) -> None:
        script = (payload.PAYLOAD / "install/lib/windows/MediaJail.ps1").read_text()
        self.assertIn("System.CodeDom.Compiler.CompilerParameters", script)
        self.assertIn("-CompilerParameters $compiler", script)
        self.assertIn("$compiler.GenerateExecutable = $true", script)
        self.assertIn("$compiler.OutputAssembly = $temporary", script)
        self.assertIn("ReferencedAssemblies.Add('System.dll')", script)
        self.assertNotIn("-CompilerOptions", script)
        self.assertNotIn("-OutputAssembly $temporary", script)

    def test_windows_native_probes_use_process_exit_codes(self) -> None:
        runtime = (payload.PAYLOAD / "install/lib/windows/Runtime.ps1").read_text(encoding="ascii")
        common = (payload.PAYLOAD / "install/lib/windows/Common.ps1").read_text(encoding="ascii")
        self.assertIn("$ErrorActionPreference = 'Continue'", runtime)
        self.assertIn("$code = $LASTEXITCODE", runtime)
        self.assertIn("Assert-ToolStarts $entry.Value $arg $entry.Key", runtime)
        self.assertIn("function Invoke-SniperNative", common)
        self.assertIn("& $Path @Arguments 2>&1 | Out-Host", common)

    def test_windows_pid_probe_never_uses_a_signal(self) -> None:
        """Windows os.kill(pid, 0) terminates the process instead of probing it."""
        source = (ROOT / "scripts/infra/sniper_lock.py").read_text()
        windows_probe = source.split("def _windows_pid_alive", 1)[1].split("\n\ndef ", 1)[0]
        self.assertIn('OpenProcess(0x1000, False, pid)', windows_probe)
        self.assertIn('GetExitCodeProcess', windows_probe)
        self.assertNotIn('os.kill', windows_probe)

    def test_generated_runtime_wrapper_uses_byte_exact_newlines(self) -> None:
        """Text-mode writes silently translate the qualified LF wrapper on Windows."""
        source = (ROOT / "scripts/producer/studio/native_runtime.py").read_text()
        self.assertIn("write_bytes(WRAPPER.encode())", source)
        self.assertNotIn("write_text(WRAPPER)", source)

    def test_windows_doctor_accepts_venv_python_across_drives(self) -> None:
        """The package venv and the locked base runtime may live on different drives."""
        source = (payload.PAYLOAD / "install/lib/doctor_setup.py").read_text()
        self.assertIn("except ValueError:", source)
        self.assertIn('APP / ".venv" if os.name == "nt" and tool == "python.exe"', source)
        self.assertNotIn("os.path.commonpath((real, os.path.realpath(prefix)))", source)

    def test_windows_media_publish_does_not_open_a_directory_as_a_file(self) -> None:
        """Windows rejects os.open(directory), unlike the POSIX durability path."""
        source = (HEADLESS / "external_media_snapshot.py").read_text()
        sync = source.split("def _sync_directory", 1)[1].split("\n\ndef ", 1)[0]
        self.assertIn('if os.name == "nt":', sync)
        self.assertLess(sync.index('if os.name == "nt":'), sync.index("os.open(path"))
        self.assertIn('if hasattr(os, "fchmod"):', source)
        self.assertEqual(source.count('getattr(os, "O_BINARY", 0)'), 2)
        identity = (HEADLESS / "external_media_verification.py").read_text()
        self.assertIn('return fields if os.name == "nt"', identity)

    def test_windows_transcription_has_a_native_process_owner(self) -> None:
        """Local Whisper must import and run without Unix fcntl or selectors."""
        common = (HEADLESS / "process_runner.py").read_text()
        windows = (HEADLESS / "windows_process_runner.py").read_text()
        whisper_io = (ROOT / "scripts/local_whisper_io.py").read_text()
        self.assertIn("except ImportError", common)
        self.assertIn("run_text_windows(request", common)
        self.assertIn("CreateJobObjectW", windows)
        self.assertIn("AssignProcessToJobObject", windows)
        self.assertIn("TerminateJobObject", windows)
        self.assertIn("child process exceeded its output byte bound", windows)
        self.assertIn('getattr(os, "O_NONBLOCK", 0)', whisper_io)
        doctor = (ROOT / "release/payload_files/install/sniper_doctor.py").read_text()
        self.assertIn('"-EncodedCommand", encoded', doctor)
        self.assertNotIn('$voice.Speak($args[1])', doctor)

    def test_workflow_runs_windows_python_failures_before_installing(self) -> None:
        workflow = (ROOT / ".github/workflows/windows-qualification.yml").read_text()
        preflight = workflow.index("release.windows_runtime_preflight")
        installer = workflow.index("Run the buyer installer")
        self.assertLess(preflight, installer)
        source = (ROOT / "release/windows_runtime_preflight.py").read_text()
        self.assertIn("module._make_speech_sample", source)
        self.assertIn("project-sniper\\nwindows-media\\x1a-preflight", source)
        self.assertIn("tokenIsAppContainer", workflow)
        self.assertIn("could not read its admitted input", workflow)
        self.assertIn("read a file that was not admitted", workflow)

    def test_shipped_agent_contract_names_the_windows_launcher(self) -> None:
        contract = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`sniper.cmd` on Windows", contract)
        self.assertIn("as shorthand; on Windows replace it with `sniper.cmd`", contract)
        self.assertNotIn("supported route runs natively on macOS.", contract)


if __name__ == "__main__":
    unittest.main()
