"""TEST-only transport/clock failures; every daemon/process call is mocked."""
from __future__ import annotations

import signal
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from headless import container_renderer as cr
from headless import render_layout_transport as transport
from headless.container_io import SealedInput
from headless.container_policy import DockerRuntime
from headless.render_layout_worker import parse_worker_request
from test_render_layout_contract import request


class LayoutTransportTests(unittest.TestCase):
    """Legacy defaults, explicit admission, original budget, mandatory cleanup."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="TEST-layout-transport-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.snapshot = self.root / "input.tar"
        self.snapshot.write_bytes(b"TEST not a real sealed archive")
        self.runtime = DockerRuntime("/TEST/docker", "/TEST/docker.sock", "sha256:" + "a" * 64, "501:20",
                                     {"labels": {"io.project-sniper.hyperframes-version": "0.7.33"}})
        self.sealed = SealedInput(str(self.snapshot), "a" * 64, ())

    def render_request(self, observed: bool = True) -> cr.RenderRequest:
        return cr.RenderRequest("compositions/agenda-slide.html", "mp4", str(self.root / "new.mp4"),
                                self.sealed, "sniper-render-" + "d" * 32, "30000/1001",
                                request() if observed else None,
                                time.monotonic() + 5 if observed else None)

    def test_default_command_never_loads_or_calls_observer(self) -> None:
        req = self.render_request(False)
        paths = cr.RenderPaths(self.runtime, str(self.root), self.sealed, str(self.root / "copied.mp4"))
        with patch.object(cr, "_layout_transport", side_effect=AssertionError("legacy imported observer")):
            command = cr._command(paths, req, req.container_name)
        self.assertNotIn("SNIPER_LAYOUT_REQUEST", "\n".join(command))
        self.assertIn("--pull", command)
        self.assertEqual(command[command.index("--fps") + 1], "30000/1001")

    def test_new_profile_cannot_use_the_current_old_image(self) -> None:
        with self.assertRaisesRegex(ValueError, "freshly built and approved"):
            transport.approved_sources(self.runtime)

    def test_layout_deadline_alone_rejects_without_loading_observer(self) -> None:
        req = replace(self.render_request(False), layout_deadline=time.monotonic() + 5)
        with patch.object(cr, "_layout_transport", side_effect=AssertionError("observer imported")):
            with self.assertRaisesRegex(RuntimeError, "requires an explicit"):
                cr._validate_request(req)

    def test_expired_request_rejects_before_image_or_seal_reads(self) -> None:
        req = self.render_request()
        expired = cr.RenderRequest(req.composition, req.fmt, req.output, req.snapshot,
                                   req.container_name, req.fps, req.layout, time.monotonic() - 1)
        with patch.object(transport, "approved_sources") as image:
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                transport.preflight(self.runtime, expired)
        image.assert_not_called()

    def test_worker_expiry_and_closed_schema_are_not_renewed(self) -> None:
        value = {"schemaVersion": 2, "operation": "observe-sealed-agenda-layout",
                 "snapshot": {"path": str(self.snapshot), "sha256": "a" * 64, "manifest": []},
                 "observation": request(), "outputPath": str(self.root / "new.mp4"),
                 "containerName": "sniper-render-" + "d" * 32, "expiresAtUnixMs": 100000}
        with patch("headless.render_layout_worker.time.time", return_value=99), \
                patch("headless.render_layout_worker.time.monotonic", return_value=50):
            self.assertEqual(parse_worker_request(value).deadline, 51)
        for expires in (99999, 100000, 701001, True):
            with patch("headless.render_layout_worker.time.time", return_value=100):
                with self.assertRaises(ValueError):
                    parse_worker_request({**value, "expiresAtUnixMs": expires})

    def test_failed_work_still_runs_cleanup_after_timer_is_disarmed(self) -> None:
        timers = []
        def cleanup(*_args) -> dict:
            timers.append(signal.getitimer(signal.ITIMER_REAL)[0])
            return {"canonicalAbsenceProved": True}
        with patch.object(cr, "required_runtime", return_value=self.runtime), \
                patch.object(transport, "preflight"), \
                patch.object(cr, "attest_image", return_value={}), \
                patch.object(cr, "daemon_identity", return_value={}), \
                patch.object(cr, "_execute_container", side_effect=RuntimeError("TEST failed worker")), \
                patch.object(cr, "remove_container", side_effect=cleanup):
            with self.assertRaisesRegex(RuntimeError, "TEST failed worker"):
                cr.render_to(self.render_request())
        self.assertEqual(timers, [0])


if __name__ == "__main__":
    unittest.main()
