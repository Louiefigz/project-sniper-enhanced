"""F5/item 9-10: provenance is checked before anything is written; a refused build leaves
no new apparent release and never touches an existing set; a successful one appears
at --out as one complete set; RELEASE.json carries the source identity, no timestamp.

The heavy staging is replaced by a small tree here; release/tests/build_integration.sh
exercises the real builder end to end in a scratch clone.

Run: .venv/bin/python -m unittest release.tests.test_build_provenance
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from release import build_package, payload
from release.stage import StageReport, StagingError

SOURCE = {"release_checkout_commit": "a" * 40, "release_checkout_tree": "b" * 40, "upstream_head": "c" * 40}
SET = {"SHA256SUMS", "release-manifest.json", "file-manifest.json", "withheld.json", "project-sniper-t-mac.zip"}


def _small_stage(root: Path, stage_dir: Path, allow_pending: bool) -> tuple[StageReport, list[str]]:
    """Stand-in for staging: a tiny tree with the buyer pages the floor check reads."""
    for page in ("START-HERE.html", "manual/index.html", "manual/install.html"):
        (stage_dir / page).parent.mkdir(parents=True, exist_ok=True)
        (stage_dir / page).write_text("Node 22.13 or newer")
    (stage_dir / "app").mkdir()
    (stage_dir / "app/x.txt").write_text("x")
    return StageReport(files=["app/x.txt"], skipped=[("secret", "withheld")]), []


class BuildProvenance(unittest.TestCase):
    """Builds into temporary output folders."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-build-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        patches = [mock.patch.object(payload, "source_facts", return_value=SOURCE),
                   mock.patch.object(build_package, "_stage", side_effect=_small_stage),
                   mock.patch.object(payload, "component_versions", return_value={"node_floor": "22.13.0"})]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _leftovers(self) -> list[str]:
        return [p.name for p in self.base.iterdir() if ".build-" in p.name]

    def test_success_promotes_exactly_one_complete_set(self) -> None:
        out = self.base / "out"
        build_package.build("t", out, False)
        self.assertEqual({p.name for p in out.iterdir()}, SET)
        self.assertEqual(self._leftovers(), [])
        with zipfile.ZipFile(out / "project-sniper-t-mac.zip") as bundle:
            release = json.loads(bundle.read("project-sniper-t/RELEASE.json"))
        self.assertEqual(release["source"]["release_checkout_commit"], "a" * 40)
        self.assertEqual(release["source"]["release_checkout_tree"], "b" * 40)
        self.assertIs(release["sellable"], False)
        self.assertNotIn("built_at_utc", json.dumps(release))
        self.assertNotIn("blockers", release)

    def test_an_existing_empty_folder_is_accepted(self) -> None:
        out = self.base / "empty"
        out.mkdir()
        build_package.build("t", out, False)
        self.assertEqual({p.name for p in out.iterdir()}, SET)

    def test_two_builds_have_identical_checksums(self) -> None:
        build_package.build("t", self.base / "a", False)
        build_package.build("t", self.base / "b", False)
        self.assertEqual((self.base / "a/SHA256SUMS").read_bytes(), (self.base / "b/SHA256SUMS").read_bytes())

    def test_dirty_checkout_writes_nothing(self) -> None:
        out = self.base / "out"
        with mock.patch.object(payload, "source_facts", side_effect=StagingError("uncommitted changes")):
            with self.assertRaises(StagingError):
                build_package.build("t", out, False)
        self.assertFalse(out.exists())
        self.assertEqual(self._leftovers(), [])

    def test_failing_scan_leaves_no_release_and_no_staging(self) -> None:
        out = self.base / "out"
        with mock.patch.object(build_package, "_stage", side_effect=StagingError("staged tree failed inspection")):
            with self.assertRaises(StagingError):
                build_package.build("t", out, False)
        self.assertFalse(out.exists())
        self.assertEqual(self._leftovers(), [])

    def test_a_prior_complete_set_is_never_touched(self) -> None:
        out = self.base / "out"
        build_package.build("t", out, False)
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        for failure in ({"_stage": StagingError("scan")}, {}):
            with self.subTest(failure=list(failure)), self.assertRaises(StagingError):
                if failure:
                    with mock.patch.object(build_package, "_stage", side_effect=failure["_stage"]):
                        build_package.build("t", out, False)
                else:
                    build_package.build("t", out, False)  # even a good build refuses an occupied folder
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)
        self.assertEqual(self._leftovers(), [])


class PayloadCopy(unittest.TestCase):
    """What write_payload copies from release/payload_files."""

    def test_byte_caches_from_local_runs_never_ship(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="sniper-payload-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        source = base / "payload_files"
        (source / "install/lib/__pycache__").mkdir(parents=True)
        (source / "install/sniper_doctor.py").write_text("print('doctor')\n")
        (source / "install/lib/__pycache__/doctor_setup.cpython-314.pyc").write_bytes(b"\x00")
        (source / "install/stray.pyc").write_bytes(b"\x00")
        stage = base / "stage"
        stage.mkdir()
        report = StageReport()
        with mock.patch.object(payload, "PAYLOAD", source), mock.patch.object(payload, "_lock_lines"):
            payload.write_payload(base, stage, report)
        self.assertEqual(sorted(report.files), ["install/sniper_doctor.py"])
        self.assertFalse(list(stage.rglob("*.pyc")))


if __name__ == "__main__":
    unittest.main()
