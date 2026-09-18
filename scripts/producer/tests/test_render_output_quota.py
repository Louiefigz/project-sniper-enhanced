"""Version-bound tmpfs tests; all Docker/image/media facts are inert TEST data."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import unittest
from dataclasses import replace
from unittest import mock

from _common import pl  # noqa: F401
from headless import container_live_policy as live
from headless import container_renderer as renderer
from headless import runtime_receipt
from test_container_policy import _expectation, _live, _runtime
from test_container_renderer import _paths
from test_runtime_receipt import _receipt

_LABEL = "io.project-sniper.hyperframes-version"


def _stored(version: object, quota: str) -> dict:
    """Build a historical TEST receipt without consulting current image approval."""
    value = copy.deepcopy(_receipt(b"TEST-media"))
    value["imageAttestation"]["Config"]["Labels"] = {_LABEL: version}
    for key in ("containerBeforeOutput", "containerAfterOutput"):
        row = value[key]
        row["Config"]["Labels"] = {_LABEL: version}
        row["HostConfig"]["Tmpfs"]["/output"] = (
            f"rw,nosuid,nodev,noexec,size={quota},uid=501,gid=20,mode=0700")
    return value


def _command(version: object) -> list[str]:
    """Construct argv only; never invoke the fake Docker executable."""
    paths = _paths()
    runtime = replace(paths.runtime, approval={"labels": {_LABEL: version}})
    request = renderer.RenderRequest("compositions/agenda-slide.html", "mp4",
                                    "/TEST/render.mp4", paths.snapshot,
                                    "sniper-render-" + "d" * 32)
    return renderer._command(replace(paths, runtime=runtime), request,
                             request.container_name)


class RenderOutputQuotaTests(unittest.TestCase):
    def test_launch_quota_is_exactly_version_bound(self) -> None:
        """New disk floor gets headroom; historical launch policy stays exact."""
        for version, quota in (("0.7.33", "1g"), ("0.8.31", "2g")):
            with self.subTest(version=version):
                command = _command(version)
                self.assertIn(f"/output:rw,nosuid,nodev,noexec,size={quota},"
                              "uid=501,gid=20,mode=0700", command)
                self.assertEqual(command[command.index("--memory") + 1], "4g")
                self.assertEqual(command[command.index("--network") + 1], "none")

    def test_unknown_missing_or_coerced_version_cannot_launch(self) -> None:
        """No fallback selects a larger writable filesystem for an unknown image."""
        for version in (None, False, 0.831, "0.8.32", "0.8.31 "):
            with self.subTest(version=version), self.assertRaises(RuntimeError):
                _command(version)

    def test_live_policy_accepts_exact_new_quota(self) -> None:
        """Actual live parser consumes stubbed daemon facts, not a live container."""
        runtime = _runtime()
        actual = _live(runtime)
        actual["HostConfig"]["Tmpfs"]["/output"] = (
            "rw,nosuid,nodev,noexec,size=2g,uid=501,gid=20,mode=0700")
        result = subprocess.CompletedProcess([], 0, json.dumps(actual), "")
        with mock.patch.object(live.subprocess, "run", return_value=result):
            self.assertEqual(live.attest_container(runtime, "/TEST/config",
                             _expectation(runtime)), actual)

    def test_offline_both_versions_keep_exact_original_quota(self) -> None:
        """Reading old evidence must not require current image/runtime discovery."""
        digest = hashlib.sha256(b"TEST-media").hexdigest()
        for version, quota in (("0.7.33", "1g"), ("0.8.31", "2g")):
            with self.subTest(version=version):
                runtime_receipt._validate(_stored(version, quota), digest)

    def test_live_policy_refuses_wrong_version_quota(self) -> None:
        """The daemon must report the one quota associated with the held image."""
        for version, quota in (("0.7.33", "2g"), ("0.8.31", "1g")):
            runtime = _runtime()
            runtime.approval["labels"][_LABEL] = version
            actual = _live(runtime)
            actual["HostConfig"]["Tmpfs"]["/output"] = (
                f"rw,nosuid,nodev,noexec,size={quota},uid=501,gid=20,mode=0700")
            result = subprocess.CompletedProcess([], 0, json.dumps(actual), "")
            with mock.patch.object(live.subprocess, "run", return_value=result), \
                    self.assertRaisesRegex(RuntimeError, "tmpfs policy"):
                live.attest_container(runtime, "/TEST/config", _expectation(runtime))

    def test_offline_unknown_or_absent_version_refuses(self) -> None:
        """Historical interpretation is explicit, never an unlabelled fallback."""
        digest = hashlib.sha256(b"TEST-media").hexdigest()
        for version in ("0.8.32", None):
            value = _stored(version, "1g")
            with self.assertRaisesRegex(RuntimeError, "unsupported renderer version"):
                runtime_receipt._validate(value, digest)

    def test_offline_cross_version_and_oversized_quotas_refuse(self) -> None:
        """Neither image may borrow the other policy or an unbounded tmpfs."""
        digest = hashlib.sha256(b"TEST-media").hexdigest()
        cases = (("0.7.33", "2g"), ("0.8.31", "1g"), ("0.8.31", "3g"))
        for version, quota in cases:
            with self.subTest(version=version, quota=quota), \
                    self.assertRaisesRegex(RuntimeError, "host policy"):
                runtime_receipt._validate(_stored(version, quota), digest)

    def test_retained_image_and_container_version_must_agree(self) -> None:
        """A version label cannot be changed independently of the image facts."""
        value = _stored("0.7.33", "1g")
        value["containerBeforeOutput"]["Config"]["Labels"][_LABEL] = "0.8.31"
        with self.assertRaisesRegex(RuntimeError, "container policy"):
            runtime_receipt._validate(value, hashlib.sha256(b"TEST-media").hexdigest())


if __name__ == "__main__":
    unittest.main()
