"""Closed body metadata and budget tests; no journal, model, media or approval."""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import file_hash
from guided_body_contract import (ACTIVATION_KEYS, REFERENCES, RUNTIME_KEYS,
                                  parse_body_activation, parse_body_input)
from guided_body_execution import assert_body_files, body_clock, hold_body_file, revalidate_body_files
from guided_opening_claim import HeldOpeningClaim, verify_claim_runtime
from guided_opening_execution import opening_clock


def body_input() -> dict:
    """TEST syntax only; these refs never authorize execution."""
    return {"schemaVersion": 1, "kind": "guided-body-media-input", "scope": "private-body-candidate-not-approval",
        "profile": "held-source-float-own-screen-body-v1", "requestId": "aaaabbbb-cccc-4ddd-8eee-ffffffffffff",
        "executionId": "11112222-3333-4444-8555-666677778888",
        "references": {key: {"path": f"/TEST/{key}.json", "sha256": "a" * 64} for key in REFERENCES},
        "runtime": {key: "TEST" for key in RUNTIME_KEYS}, "selectedGraphicOrders": list(range(12))}


def body_activation() -> dict:
    """TEST closed activation shape, not independently held server permission."""
    value = body_input()
    row = {key: "a" * 64 for key in ACTIVATION_KEYS}
    row.update(schemaVersion=1, kind="guided-body-execution-activation",
        scope="private-body-owned-execution-not-approval", requestId=value["requestId"],
        executionId=value["executionId"], inputPath="/TEST/input.json", outputRoot="/TEST/output",
        generationStartedAt="2026-09-07T00:00:00.000Z", createdAt="2026-09-07T00:01:00.000Z",
        selectedGraphicOrders=list(range(12)), runtime=value["runtime"])
    return row


class GuidedBodyContractTests(unittest.TestCase):
    """Body work is distinct; old limits and non-executable admission stay intact."""

    def test_closed_input_and_activation_preserve_all_twelve_rows(self) -> None:
        row, activation = body_input(), body_activation()
        self.assertEqual(parse_body_input(row), row)
        self.assertEqual(parse_body_activation(activation), activation)

    def test_unknown_flags_or_admission_role_never_activate(self) -> None:
        for key, value in (("executable", True), ("deliveryApproved", True), ("kind", "guided-body-execution-claim")):
            row = body_activation()
            row[key] = value
            with self.subTest(key=key):
                with self.assertRaises(RuntimeError):
                    parse_body_activation(row)

    def test_subset_duplicate_bool_or_excess_orders_block(self) -> None:
        for orders in ([0, 2], [0, 0], [False], list(range(129))):
            row = body_input()
            row["selectedGraphicOrders"] = orders
            with self.assertRaises(RuntimeError):
                parse_body_input(row)

    def test_unsafe_path_uuid_and_clock_types_block(self) -> None:
        for value in ("/TEST/../file", "/TEST//file", "/TEST/./file", "/TEST/\x00file", "relative"):
            row = body_input()
            row["references"]["heldInput"]["path"] = value
            with self.assertRaises(RuntimeError):
                parse_body_input(row)
        for value in (True, "aaaabbbb-cccc-4ddd-0eee-ffffffffffff", "AAAABBBB-CCCC-4DDD-8EEE-FFFFFFFFFFFF"):
            row = body_input()
            row["requestId"] = value
            with self.assertRaises(RuntimeError):
                parse_body_input(row)
        row = body_activation()
        row["createdAt"] = "2026-09-06T00:00:00.000Z"
        with self.assertRaises(RuntimeError):
            parse_body_activation(row)

    def test_body_clock_does_not_widen_opening_or_reset_phase_budget(self) -> None:
        with patch("time.monotonic", return_value=100.0):
            clock = body_clock(3300)
        with patch("time.monotonic", return_value=101.0):
            self.assertEqual(clock.remaining(), 3299)
        with self.assertRaisesRegex(RuntimeError, "25 minutes"):
            opening_clock(3300)
        for value in (True, 0, 3301, float("nan"), float("inf")):
            with self.assertRaises(RuntimeError):
                body_clock(value)

    def test_shared_runtime_extraction_preserves_original_wrapper(self) -> None:
        claim = HeldOpeningClaim(Path("/TEST/claim"), "a" * 64, {"runtime": {"TEST": "same object"}})
        with patch("guided_opening_claim.verify_runtime_controls") as guard:
            verify_claim_runtime(claim, "/TEST/snapshot")
        guard.assert_called_once_with(claim.value["runtime"], "/TEST/snapshot")

    def test_cheap_metadata_guard_detects_same_bytes_rewrite_and_terminal_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "control.json"
            path.write_bytes(b"TEST immutable control")
            held = hold_body_file(path, file_hash(path))
            clock = body_clock(10)
            assert_body_files((held,), clock)
            revalidate_body_files((held,), clock)
            path.write_bytes(b"TEST immutable control")
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                assert_body_files((held,), clock)
            with patch.object(clock, "remaining", side_effect=RuntimeError("TEST expired")):
                with self.assertRaisesRegex(RuntimeError, "expired"):
                    assert_body_files((), clock)

    def test_metadata_fifo_symlink_hardlink_and_wrong_hash_reject_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            regular = root / "regular"
            regular.write_bytes(b"TEST")
            fifo, link, hard = root / "fifo", root / "link", root / "hard"
            os.mkfifo(fifo)
            link.symlink_to(regular)
            os.link(regular, hard)
            for path in (fifo, link, hard):
                with self.subTest(path=path.name):
                    with self.assertRaises(RuntimeError):
                        hold_body_file(path, "0" * 64)
            hard.unlink()
            with self.assertRaisesRegex(RuntimeError, "bytes changed"):
                hold_body_file(regular, "0" * 64)


if __name__ == "__main__":
    unittest.main()
