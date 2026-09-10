"""Bounded dispatch regressions: actual scene validation, inert Python leaves only."""
from __future__ import annotations

import signal
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from color.deadline import wall_budget
from graphics import scene_render as renderer
from graphics import render_cache
from graphics.scene_contract import SceneContractError
from headless.process_runner import ProcessDeadlineError
from scene_fixtures import fire_sparkles_scene


class SceneUnitDispatchTests(unittest.TestCase):
    """Single-worker dispatch must keep the existing caller's interrupt authority."""

    def setUp(self) -> None:
        """Build data-only requests; the sole render leaf never touches files."""
        self.scene = fire_sparkles_scene("a" * 64)
        self.scene["renderUnits"].reverse()
        self.bundle = object()
        self.cache = "/TEST-unused-scene-dispatch"

    def test_single_worker_preserves_caller_order_and_exact_requests(self) -> None:
        """A serial request must not construct a pool or change receipt identity."""
        caller = threading.get_ident()
        observed = []
        receipts = {key: {"unitId": key} for key in ("unit-left", "unit-right")}

        def render(request: renderer.SceneRenderRequest) -> dict:
            """Record actual dispatch metadata without native or cache work."""
            observed.append((request, threading.get_ident()))
            return receipts[request.unit_id]

        with patch.object(renderer, "render_scene", side_effect=render):
            result = renderer.render_scene_units(self.scene, self.bundle, self.cache, 1)
        self.assertEqual([row[0].unit_id for row in observed], ["unit-left", "unit-right"])
        self.assertTrue(all(row[1] == caller for row in observed))
        self.assertTrue(all(row[0].bundle is self.bundle for row in observed))
        self.assertTrue(all(row[0].scene is self.scene for row in observed))
        self.assertTrue(all(row[0].cache_dir == self.cache for row in observed))
        self.assertIs(result[0], receipts["unit-left"])
        self.assertIs(result[1], receipts["unit-right"])

    @unittest.skipUnless(hasattr(signal, "setitimer"), "requires actual POSIX timer")
    def test_single_worker_interrupts_running_leaf_and_stops_later_units(self) -> None:
        """Expiry reaches the active leaf's finally instead of waiting for success."""
        events = []
        previous = signal.getsignal(signal.SIGALRM)

        def render(request: renderer.SceneRenderRequest) -> dict:
            """Use an interruptible Python sleep, never a media/native operation."""
            events.append((request.unit_id, "enter"))
            try:
                time.sleep(0.3)
                events.append((request.unit_id, "completed"))
                return {"unitId": request.unit_id}
            finally:
                events.append((request.unit_id, "cleanup"))

        with patch.object(renderer, "render_scene", side_effect=render), \
                self.assertRaisesRegex(RuntimeError, "deadline"):
            with wall_budget(time.monotonic() + 0.05):
                renderer.render_scene_units(self.scene, self.bundle, self.cache, 1)
        self.assertEqual(events, [("unit-left", "enter"), ("unit-left", "cleanup")])
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        self.assertIs(signal.getsignal(signal.SIGALRM), previous)

    def test_multiple_workers_keep_parallel_branch_and_sorted_results(self) -> None:
        """A requested pool retains its original noncaller execution and result order."""
        observed = []
        caller = threading.get_ident()

        def render(request: renderer.SceneRenderRequest) -> dict:
            """Return an inert receipt from whichever original pool thread runs it."""
            observed.append(threading.get_ident())
            return {"unitId": request.unit_id}

        with patch.object(renderer, "render_scene", side_effect=render):
            result = renderer.render_scene_units(self.scene, self.bundle, self.cache, 2)
        self.assertEqual([row["unitId"] for row in result], ["unit-left", "unit-right"])
        self.assertTrue(all(thread != caller for thread in observed))

    def test_invalid_workers_refuse_before_any_render(self) -> None:
        """Strict worker validation remains unchanged for bools and invalid counts."""
        render = self.enterContext(patch.object(renderer, "render_scene"))
        for value in (True, False, 0, 5, 1.0, "1"):
            with self.assertRaisesRegex(SceneContractError, "workers"):
                renderer.render_scene_units(self.scene, self.bundle, self.cache, value)
        render.assert_not_called()

    @unittest.skipUnless(hasattr(signal, "setitimer"), "requires actual POSIX timer")
    def test_cache_hit_deadline_does_not_become_a_rebuild_miss(self) -> None:
        """Budget expiry is cancellation, not evidence of corrupt cached media."""
        misses = []

        def proof(*args: object) -> dict:
            """Block only in Python; the original timer must interrupt this leaf."""
            time.sleep(0.15)
            raise AssertionError("proof should have been interrupted")

        with patch.object(render_cache.os.path, "lexists", return_value=True), \
                patch.object(render_cache, "_proved_hit", side_effect=proof), \
                patch.object(render_cache, "_quarantine") as quarantine, \
                self.assertRaisesRegex(RuntimeError, "deadline"):
            with wall_budget(time.monotonic() + 0.03):
                misses.append(render_cache._existing_hit("/TEST-unused-cache", proof))
        self.assertEqual(misses, [])
        quarantine.assert_not_called()

    def test_typed_proof_timeouts_propagate_without_quarantine(self) -> None:
        """Timeouts are not corruption; the original exception must reach the caller."""
        cases = (ProcessDeadlineError("TEST deadline"), TimeoutError("TEST timeout"),
                 subprocess.TimeoutExpired("TEST child never started", 1))
        self.enterContext(patch.object(render_cache.os.path, "lexists", return_value=True))
        proof = self.enterContext(patch.object(render_cache, "_proved_hit"))
        quarantine = self.enterContext(patch.object(render_cache, "_quarantine"))
        for error in cases:
            proof.side_effect = error
            with self.assertRaises(type(error)) as caught:
                render_cache._existing_hit("/TEST-unused-cache", object())
            self.assertIs(caught.exception, error)
        quarantine.assert_not_called()

    def test_invalid_media_errors_still_invalidate_the_cache(self) -> None:
        """The narrow timeout distinction preserves existing corrupt-hit behavior."""
        self.enterContext(patch.object(render_cache.os.path, "lexists", return_value=True))
        proof = self.enterContext(patch.object(render_cache, "_proved_hit"))
        quarantine = self.enterContext(patch.object(render_cache, "_quarantine"))
        for error in (RuntimeError("TEST invalid decode"), ValueError("TEST format"),
                      OSError("TEST invalid file")):
            proof.side_effect = error
            self.assertIsNone(render_cache._existing_hit("/TEST-unused-cache", object()))
        self.assertEqual(quarantine.call_count, 3)


if __name__ == "__main__":
    unittest.main()
