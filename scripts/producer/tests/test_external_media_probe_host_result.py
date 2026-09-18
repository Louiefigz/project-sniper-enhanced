"""Host-mounted result and decoder-stderr admission regressions."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from headless.external_media_probe import MAX_RESULT_BYTES, _read_result
from headless.external_media_probe_policy import NODE_PROBE, _valid_mount


def _result_root(root: Path) -> Path:
    result = root / "result"
    result.mkdir(mode=0o700)
    return result


class ExternalMediaHostResultTests(unittest.TestCase):
    """The host reads one immutable bounded file without docker exec polling."""

    def test_reads_exact_regular_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = _result_root(root) / "result.json"
            result.write_text('{"schemaVersion":1}\n', encoding="utf-8")
            value = _read_result(None, str(root), "unused-container")
            self.assertEqual(value, '{"schemaVersion":1}\n')

    def test_missing_result_is_not_yet_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _result_root(root)
            self.assertIsNone(_read_result(None, str(root), "unused"))

    def test_symlink_hardlink_and_oversize_results_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result_dir = _result_root(root)
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            result = result_dir / "result.json"
            result.symlink_to(target)
            with self.assertRaises(OSError):
                _read_result(None, str(root), "unused")
            result.unlink()
            os.link(target, result)
            with self.assertRaisesRegex(RuntimeError, "bounded"):
                _read_result(None, str(root), "unused")
            result.unlink()
            result.write_bytes(b"x" * (MAX_RESULT_BYTES + 1))
            with self.assertRaisesRegex(RuntimeError, "bounded"):
                _read_result(None, str(root), "unused")

    def test_mount_attestation_requires_exact_read_and_write_mounts(self) -> None:
        observed = SimpleNamespace(
            source="/source.media",
            result_dir="/host/result",
            actual={"Mounts": [
                {"Source": "/source.media", "Destination": "/input/media",
                 "RW": False},
                {"Source": "/host/result", "Destination": "/scratch",
                 "RW": True},
            ]},
        )
        self.assertTrue(_valid_mount(observed))
        observed.actual["Mounts"][1]["RW"] = False
        self.assertFalse(_valid_mount(observed))

    @unittest.skipUnless(shutil.which("node"), "node required")
    def test_status_zero_decoder_stderr_publishes_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, output = root / "media.bin", root / "result.json"
            source.write_bytes(b"not-a-special-media-header")
            script = NODE_PROBE.replace(
                "const cp=require('node:child_process'),fs=require('node:fs');",
                "const fs=require('node:fs'),cp={spawnSync:()=>({"
                "status:0,signal:null,stdout:'{}',stderr:'decoded frame error'})};",
            ).replace(
                "const input='/input/media',output='/scratch/result.json';",
                f"const input={json.dumps(str(source))},"
                f"output={json.dumps(str(output))};",
            ).replace("setTimeout(()=>{},30000)", "void 0")
            run = subprocess.run(
                ["node", "-e", script, "1024", "8192", "8192", "100",
                 "60", "2", "90"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertIs(document["ok"], False)
            self.assertEqual(document["code"], "decoded frame error")
            self.assertFalse((root / "result.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
