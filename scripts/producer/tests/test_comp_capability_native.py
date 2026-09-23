"""Native catalog qualification refuses unowned work and stale source records."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import graphics.comp_capability_native as native
from studio.native_runtime import digest


class NativeCapabilityAdmissionTests(unittest.TestCase):
    """Synthetic owner records test admission only; they never render media."""

    def setUp(self) -> None:
        """Build explicit TEST-only inputs under a canonical private root."""
        self.temporary = tempfile.TemporaryDirectory(prefix="TEST-native-capability-")
        self.root = Path(self.temporary.name).resolve()
        self.file = self.root / "request.json"
        self.pin = self.root / "TEST-code.py"
        self.pin.write_text("# TEST pin; never executed\n")
        self.request = {"scope": "catalog-capability-inspection-v1",
                        "project": native.MOTION_DIR, "entry": native.entry_for("line-swap"),
                        "sourceDigest": native.current_source_digest(),
                        "pins": {str(self.pin): digest(self.pin)}}
        self.file.write_text(json.dumps(self.request))
        self.owner = {
            "project": native.MOTION_DIR, "output": str(self.root / "result.json"),
            "args": [native.sys.executable, "-B", str(native.HERE), "--worker", str(self.file)],
            "status": "running", "additionalFilePinsBefore": {str(self.file): digest(self.file)},
        }
        self.owner_file = self.root / "native.render.json"
        self.owner_file.write_text(json.dumps(self.owner))
        self.environment = patch.dict(os.environ, {
            "SNIPER_CAPABILITY_REQUEST": str(self.file),
            "SNIPER_CAPABILITY_OWNER": str(self.owner_file),
            "SNIPER_CAPABILITY_PID": str(os.getpid()),
        })
        self.environment.start()

    def tearDown(self) -> None:
        """Remove only this test's private synthetic records."""
        self.environment.stop()
        self.temporary.cleanup()

    def write_request(self) -> None:
        """Bind a deliberately changed synthetic request to its TEST owner."""
        self.file.write_text(json.dumps(self.request))
        self.owner["additionalFilePinsBefore"][str(self.file)] = digest(self.file)
        self.owner_file.write_text(json.dumps(self.owner))

    def test_current_bounded_default_request(self) -> None:
        """Admission recognizes the exact source state without creative approval."""
        self.assertEqual(native.require_worker(self.file), self.request)

    def test_no_owner_refuses_before_media(self) -> None:
        """Direct invocation must not reach the component renderer."""
        with patch.dict(os.environ, {"SNIPER_CAPABILITY_REQUEST": ""}), \
                patch.object(native, "render_entry_for_capability_probe") as render:
            with self.assertRaisesRegex(ValueError, "shared native owner"):
                native.worker(self.file)
            render.assert_not_called()

    def test_terminal_or_different_owner_refuses(self) -> None:
        """Completion and unrelated output/argv never authorize a new render."""
        for change in ({"completedAt": "TEST done"}, {"abortReason": "TEST stopped"},
                       {"output": str(self.root / "other.json")}, {"args": ["other-worker"]}):
            with self.subTest(change=change):
                self.owner_file.write_text(json.dumps({**self.owner, **change}))
                with self.assertRaisesRegex(ValueError, "exact live worker"):
                    native.require_worker(self.file)

    def test_changed_implementation_refuses(self) -> None:
        """A valid owner cannot conceal changed executable inputs."""
        self.pin.write_text("# TEST changed\n")
        with self.assertRaisesRegex(ValueError, "implementation changed"):
            native.require_worker(self.file)

    def test_changed_motion_closure_refuses(self) -> None:
        """An old matrix source identity cannot admit current measurements."""
        self.request["sourceDigest"] = "0" * 64
        self.write_request()
        with self.assertRaisesRegex(ValueError, "sources changed"):
            native.require_worker(self.file)

    def test_arbitrary_parameters_and_retired_kind_refuse(self) -> None:
        """The inspection route cannot become an arbitrary video exporter."""
        self.request["entry"]["outEnd"] = 300
        self.write_request()
        with self.assertRaisesRegex(ValueError, "current defaults"):
            native.require_worker(self.file)
        with self.assertRaises(ValueError):
            native.entry_for("section-marker")


if __name__ == "__main__":
    unittest.main()
