"""Closed 30fps result-reader protocol; no retired execution or receipt upgrade."""
from __future__ import annotations

from types import SimpleNamespace
from collections.abc import Callable
from unittest import mock

from _render_result_fixture import HistoricalResultFixture


class CurrentRenderProtocolTests(HistoricalResultFixture):
    """Closed result-reader protocol applied to inert TEST proof metadata."""

    def test_fixed_rate_is_retained_without_changing_proved_clock(self) -> None:
        value, _ = self._validate(self._value())
        self.assertEqual(value["fps"], "30")
        self.assertEqual(value["proof"]["asset"]["fps"], 30)
        self.assertEqual(value["proof"]["asset"]["frameCount"], 75)

    def test_shared_materializer_serializer_matches_result_reader(self) -> None:
        """Only serialization is exercised; no source or media is executed."""
        from graphics.graphics_render import _materialize_work
        value = self._value()
        work = SimpleNamespace(key=value["key"], entry={"kind": "section-marker"},
                               fmt="mov", fps=30)
        with mock.patch("graphics.graphics_render.materialize", return_value=(
                value["path"], False, value["proof"])):
            materialized = _materialize_work(work, str(self.attempt), "mov")
        result, _ = self._validate(materialized)
        self.assertEqual(result["fps"], "30")

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

    def reject(self, mutation: Callable[[dict], None], message: str) -> None:
        """Exercise real result-reader validation on independently tampered proof."""
        value = self._value()
        mutation(value)
        self._rewrite_sidecar(value)
        with self.assertRaisesRegex(RuntimeError, message):
            self._validate(value)
