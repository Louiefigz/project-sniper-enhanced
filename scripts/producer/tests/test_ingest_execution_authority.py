"""Execution-boundary tests for mandatory source-set authority."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ingest
from _ingest_admission_fixture import probe as _probe
from _ingest_admission_fixture import runner as _runner
from ingest_execution_authority import verify_execution_media_authority


class IngestExecutionAuthorityTests(unittest.TestCase):
    def test_execution_rejects_unbound_manifest_rows_and_direct_music(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "output"
            (root / "broll").mkdir()
            (root / "music").mkdir()
            (root / "take.mp4").write_bytes(b"video")
            (root / "broll" / "shot.png").write_bytes(b"image")
            (root / "music" / "bed.wav").write_bytes(b"music")
            manifest_path = out / "asset_manifest.json"
            with patch("ingest_admission.admit_external_media",
                       side_effect=_runner), \
                    patch("ingest_admitted_sources.probe_media",
                          side_effect=_probe), \
                    patch("ingest_admitted_scan.probe_media",
                          side_effect=_probe), \
                    patch("ingest.scan_builtin_music", return_value=[]):
                manifest = ingest.build_manifest(root, out, no_transcribe=True)
            manifest_path.write_text(json.dumps(manifest))
            music = manifest["music"][0]
            with patch(
                "ingest_admission_contract.verify_external_media_snapshot"
            ) as snapshot_check:
                verify_execution_media_authority(
                    {"music": {"enabled": True, "assetId": music["id"]}},
                    manifest, str(manifest_path))
            self.assertEqual(snapshot_check.call_count, 3)
            verify_execution_media_authority(
                {"music": {"enabled": True, "path": music["path"]}},
                manifest, str(manifest_path))

            outside = root / "outside.wav"
            outside.write_bytes(b"outside")
            with self.assertRaisesRegex(RuntimeError, "direct music.path"):
                verify_execution_media_authority(
                    {"music": {"enabled": True, "path": str(outside)}},
                    manifest, str(manifest_path))
            with self.assertRaisesRegex(RuntimeError, "absolute admitted"):
                verify_execution_media_authority(
                    {"music": {
                        "enabled": True,
                        "assetId": music["id"],
                        "path": "relative-bed.wav",
                    }},
                    manifest, str(manifest_path))

            tampered = json.loads(json.dumps(manifest))
            tampered["sources"][0]["path"] = str(outside)
            with self.assertRaisesRegex(RuntimeError, "disagrees"):
                verify_execution_media_authority(
                    {}, tampered, str(manifest_path))

            late = json.loads(json.dumps(manifest))
            late["broll"].append({"id": "late", "path": str(outside)})
            with self.assertRaisesRegex(RuntimeError, "lacks admitted"):
                verify_execution_media_authority({}, late, str(manifest_path))

            repeated_id = json.loads(json.dumps(manifest))
            repeated_id["sources"].append(dict(repeated_id["sources"][0]))
            with self.assertRaisesRegex(RuntimeError, "repeats an asset id"):
                verify_execution_media_authority(
                    {}, repeated_id, str(manifest_path))

            repeated_projection = json.loads(json.dumps(manifest))
            duplicate = dict(repeated_projection["sources"][0])
            duplicate["id"] = "second-id-for-the-same-ingress"
            original = Path(duplicate["originalPath"])
            duplicate["originalPath"] = (
                f"{original.parent}{os.sep}.{os.sep}{original.name}")
            repeated_projection["sources"].append(duplicate)
            with self.assertRaisesRegex(
                    RuntimeError, "repeats an admitted ingress projection"):
                verify_execution_media_authority(
                    {}, repeated_projection, str(manifest_path))

    def test_render_and_assemble_reject_bad_binding_before_media_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "edit_plan.json"
            manifest = root / "asset_manifest.json"
            plan.write_text("{}")
            manifest.write_text(json.dumps({"sourceSetAdmission": {}}))
            producer = Path(__file__).parents[1]
            commands = [
                [sys.executable, str(producer / "render.py"), str(plan),
                 str(manifest), str(root / "render"), "--no-audit"],
                [sys.executable, str(producer / "assemble.py"),
                 str(root / "base.mp4"), str(plan), str(root / "final.mp4"),
                 "--manifest", str(manifest)],
            ]
            for command in commands:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=20,
                    check=False, cwd=producer)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "source-set admission binding is malformed",
                    result.stdout + result.stderr)

    def test_palmier_entrypoints_reject_bad_binding_before_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "edit_plan.json"
            manifest = root / "asset_manifest.json"
            plan.write_text("{}")
            manifest.write_text(json.dumps({"sourceSetAdmission": {}}))
            producer = Path(__file__).parents[1]
            commands = [
                [
                    sys.executable,
                    str(producer / "palmier" / "checkpoint_cli.py"),
                    str(plan), str(manifest), str(root),
                    "--stage", "cut", "--require-source-set-admission",
                ],
                [
                    sys.executable, str(producer / "palmier" / "push.py"),
                    str(plan), str(manifest),
                    "--require-source-set-admission",
                ],
                [
                    sys.executable, str(producer / "palmier" / "draft.py"),
                    str(manifest), str(root / "draft"),
                    "--require-source-set-admission",
                    "--name", "authority-test", "--mode", "longform",
                ],
                [
                    sys.executable,
                    str(producer / "palmier" / "desktop_cli.py"),
                    "--repo", str(root),
                    "--require-source-set-admission",
                    "begin", str(root / "desktop"), str(plan), str(manifest),
                    "--stage", "cut",
                ],
            ]
            for command in commands:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=20,
                    check=False, cwd=producer,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "source-set admission binding is malformed",
                    result.stdout + result.stderr,
                )

    def test_canonical_product_mode_rejects_legacy_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "asset_manifest.json"
            manifest.write_text(json.dumps({"sources": []}))
            with patch.dict(
                    os.environ,
                    {"SNIPER_REQUIRE_SOURCE_SET_ADMISSION": "1"}):
                with self.assertRaisesRegex(
                        RuntimeError, "mandatory source-set admission"):
                    from ingest_admission_contract import \
                        verify_manifest_source_set_if_present
                    verify_manifest_source_set_if_present(
                        {"sources": []}, str(manifest))

    def test_direct_assemble_defaults_to_mandatory_admission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "edit_plan.json"
            plan.write_text("{}")
            producer = Path(__file__).parents[1]
            result = subprocess.run(
                [
                    sys.executable, str(producer / "assemble.py"),
                    str(root / "base.mp4"), str(plan),
                    str(root / "final.mp4"),
                ],
                capture_output=True, text=True, timeout=20,
                check=False, cwd=producer,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "mandatory source-set admission requires a resolved manifest",
                result.stdout + result.stderr,
            )

    def test_direct_render_defaults_to_mandatory_admission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "edit_plan.json"
            manifest = root / "asset_manifest.json"
            plan.write_text("{}")
            manifest.write_text(json.dumps({"sources": []}))
            producer = Path(__file__).parents[1]
            result = subprocess.run(
                [
                    sys.executable, str(producer / "render.py"),
                    str(plan), str(manifest), str(root / "output"),
                    "--no-audit",
                ],
                capture_output=True, text=True, timeout=20,
                check=False, cwd=producer,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "mandatory source-set admission",
                result.stdout + result.stderr,
            )

    def test_direct_palmier_clis_default_to_mandatory_admission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "edit_plan.json"
            manifest = root / "asset_manifest.json"
            plan.write_text("{}")
            manifest.write_text(json.dumps({"sources": []}))
            producer = Path(__file__).parents[1]
            commands = [
                [
                    sys.executable,
                    str(producer / "palmier" / "checkpoint_cli.py"),
                    str(plan), str(manifest), str(root), "--stage", "cut",
                ],
                [
                    sys.executable, str(producer / "palmier" / "push.py"),
                    str(plan), str(manifest),
                ],
                [
                    sys.executable, str(producer / "palmier" / "draft.py"),
                    str(manifest), str(root / "draft"),
                    "--name", "authority-test", "--mode", "longform",
                ],
                [
                    sys.executable,
                    str(producer / "palmier" / "desktop_cli.py"),
                    "--repo", str(root), "begin", str(root / "desktop"),
                    str(plan), str(manifest), "--stage", "cut",
                ],
            ]
            for command in commands:
                with self.subTest(command=Path(command[1]).name):
                    result = subprocess.run(
                        command, capture_output=True, text=True,
                        timeout=20, check=False, cwd=producer,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "mandatory source-set admission",
                        result.stdout + result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
