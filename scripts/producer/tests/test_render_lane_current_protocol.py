"""Current sealed 30fps worker protocol, not historical receipt upgrades."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest import mock

from _render_lane_fixture import RenderLaneFixture
from headless.render_lane import RenderExecutionPolicy, launch_overlay


class CurrentRenderProtocolTests(RenderLaneFixture):
    """Match the real materializer's closed result, including its exact token."""

    def response(self, request, mutation):
        """Change only one live-result protocol field in a synthetic proof."""
        original = self._fake_success(request)
        value = json.loads(original.stdout)
        mutation(value)
        return subprocess.CompletedProcess(original.args, 0, json.dumps(value), "")

    def test_current_fixed_rate_is_retained_without_changing_proved_clock(self) -> None:
        with mock.patch("headless.render_lane.run_text", side_effect=self._fake_success):
            result = launch_overlay(RenderExecutionPolicy("sealed-oci-v2"), self._request(), self._runtime())
        self.assertEqual(result["result"]["fps"], "30")
        self.assertEqual(result["result"]["proof"]["asset"]["fps"], 30)
        self.assertEqual(result["result"]["proof"]["asset"]["frameCount"], 75)

    def test_actual_shared_materializer_shape_reaches_parent_contract(self) -> None:
        from graphics.graphics_render import _materialize_work
        def actual_shape(request):
            original = self._fake_success(request)
            value = json.loads(original.stdout)
            work = SimpleNamespace(key=value["key"], entry={"kind": "section-marker"}, fmt="mov", fps=30)
            with mock.patch("graphics.graphics_render.materialize", return_value=(value["path"], False, value["proof"])):
                materialized = _materialize_work(work, str(self.attempt), "mov")
            return subprocess.CompletedProcess(original.args, 0, json.dumps(materialized), "")
        with mock.patch("headless.render_lane.run_text", side_effect=actual_shape):
            result = launch_overlay(RenderExecutionPolicy("sealed-oci-v2"), self._request(), self._runtime())
        self.assertEqual(result["result"]["fps"], "30")

    def test_noncanonical_or_unqualified_rates_are_not_admitted(self) -> None:
        for rate in (30, "30/1", "24", "30000/1001", None, True):
            with self.subTest(rate=rate):
                self.reject(lambda row: row.update(fps=rate), "invalid result values")

    def test_current_protocol_does_not_implicitly_upgrade_old_missing_rate(self) -> None:
        self.reject(lambda row: row.pop("fps"), "invalid result schema")

    def test_current_protocol_stays_closed_to_unknown_fields(self) -> None:
        self.reject(lambda row: row.update(unreviewedExtra=True), "invalid result schema")

    def test_claimed_rate_cannot_override_disagreeing_media_proof(self) -> None:
        self.reject(lambda row: row["proof"]["asset"].update(fps=24), "asset does not match")

    def reject(self, mutation, message: str) -> None:
        """Exercise actual parent validation without a container or output claim."""
        with mock.patch("headless.render_lane.run_text", side_effect=lambda request: self.response(request, mutation)):
            with self.assertRaisesRegex(RuntimeError, message):
                launch_overlay(RenderExecutionPolicy("sealed-oci-v2"), self._request(), self._runtime())
