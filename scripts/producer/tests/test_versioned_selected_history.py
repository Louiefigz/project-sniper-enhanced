"""Real-disk adversarial tests for recursive versioned selected history."""

from __future__ import annotations

import dataclasses
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _versioned_history_tree import VersionedHistoryTreeFixture
from headless.generation_schema import parse_current_pointer
import headless.historical_generation_store as store_module
from headless.versioned_history_binding import bind_versioned_selected_history
from headless.versioned_history_resolver import resolve_versioned_selected_history
from headless.versioned_history_types import (
    VERSIONED_SELECTED_HISTORY_SCOPE,
    VERSIONED_SELECTED_HISTORY_STATUS,
    GenesisHistoryAuthorityV1,
    VersionedHistoryBindingInputsV1,
    VersionedHistoryNodeV1,
    VersionedSelectedHistoryError,
    VersionedSelectedHistoryReportV1,
)
from headless.versioned_history_binding import (
    require_versioned_history_execution_authorized,
)


class VersionedSelectedHistoryTests(unittest.TestCase):
    def test_mixed_r1_v2_r0_v2_chain_binds_recursively(self) -> None:
        fixture = VersionedHistoryTreeFixture()
        try:
            result = resolve_versioned_selected_history(str(fixture.authority))
            self.assertEqual(result.status, VERSIONED_SELECTED_HISTORY_STATUS)
            self.assertEqual(result.proof_scope, VERSIONED_SELECTED_HISTORY_SCOPE)
            self.assertEqual(result.lineage_node_count, 4)
            self.assertEqual(result.lineage_edges_required, 3)
            self.assertEqual(result.lineage_edges_verified, 3)
            self.assertTrue(result.selected_current_ancestry_verified)
            self.assertTrue(result.unique_genesis_tail_verified)
            self.assertTrue(result.recursive_lineage_verified)
            self.assertTrue(result.genesis_origin_verified)
            self.assertFalse(result.global_fork_uniqueness_verified)
            self.assertFalse(result.final_current_and_fence_rechecked)
            self.assertFalse(result.runtime_verified)
            self.assertFalse(result.execution_authorized)
            self.assertFalse(result.publication_authorized)
            self.assertEqual(
                tuple(node.approved_card_class for node in result.nodes),
                (
                    "quality-pass-approved-card-v2",
                    "approved-parent-v1",
                    "quality-pass-approved-card-v2",
                    "genesis-approved-card-v2",
                ),
            )
            self.assertEqual(
                tuple(node.authority_receipt_class for node in result.nodes),
                (
                    "assembly-receipt-v2",
                    "assembly-receipt-v1",
                    "assembly-receipt-v2",
                    "initialization-origin-receipt-v1",
                ),
            )
            self.assertNotIn(str(fixture.root), repr(result))
        finally:
            fixture.close()

    def test_unselected_fork_does_not_become_global_uniqueness_claim(self) -> None:
        fixture = VersionedHistoryTreeFixture(include_fork=True)
        try:
            result = resolve_versioned_selected_history(str(fixture.authority))
            self.assertTrue(result.recursive_lineage_verified)
            self.assertEqual(result.lineage_node_count, 4)
            self.assertFalse(result.global_fork_uniqueness_verified)
            self.assertIn("no-global-fork-claim", result.proof_scope)
        finally:
            fixture.close()

    def test_cycle_gap_wrong_tail_receipt_and_class_relabel_reject(self) -> None:
        scenarios = (
            "cycle",
            "bad-sequence",
            "wrong-genesis-tail",
            "wrong-parent-receipt",
            "wrong-genesis-receipt-kind",
            "class-relabel",
        )
        for scenario in scenarios:
            fixture = VersionedHistoryTreeFixture(scenario)
            try:
                with self.subTest(scenario=scenario), self.assertRaises(
                    VersionedSelectedHistoryError
                ):
                    resolve_versioned_selected_history(str(fixture.authority))
            finally:
                fixture.close()

    def test_stale_committed_bytes_reject(self) -> None:
        fixture = VersionedHistoryTreeFixture()
        try:
            fixture.corrupt_head_artifact()
            with self.assertRaises(VersionedSelectedHistoryError):
                resolve_versioned_selected_history(str(fixture.authority))
        finally:
            fixture.close()

    def test_hostile_string_cannot_bypass_canonical_root_requirement(self) -> None:
        class HostilePath(str):
            def __eq__(self, _other: object) -> bool:
                return True

            def __ne__(self, _other: object) -> bool:
                return False

        fixture = VersionedHistoryTreeFixture()
        try:
            alias = HostilePath(str(fixture.authority / ".." / "authority"))
            with self.assertRaises(VersionedSelectedHistoryError):
                resolve_versioned_selected_history(alias)
        finally:
            fixture.close()

    def test_hostile_exact_node_fields_fail_with_contract_error(self) -> None:
        fixture = VersionedHistoryTreeFixture()
        try:
            anchor = parse_current_pointer((fixture.authority / "CURRENT").read_bytes())
            node = VersionedHistoryNodeV1(
                None,
                "forged-profile",
                "forged-class",
                None,
                GenesisHistoryAuthorityV1(None),
            )
            inputs = VersionedHistoryBindingInputsV1(anchor, (node,))
            with self.assertRaises(VersionedSelectedHistoryError):
                bind_versioned_selected_history(inputs)
        finally:
            fixture.close()

    def test_recursive_store_uses_bounded_directory_enumeration(self) -> None:
        fixture = VersionedHistoryTreeFixture()
        calls: list[int] = []
        exact_entries = store_module._exact_entries

        def observed(fd: int, expected: set[str] | frozenset[str]) -> bool:
            calls.append(len(expected))
            return exact_entries(fd, expected)

        try:
            with patch.object(store_module, "_exact_entries", observed), patch.object(
                store_module.os,
                "listdir",
                side_effect=AssertionError("unbounded listdir used"),
            ):
                result = resolve_versioned_selected_history(str(fixture.authority))
            self.assertEqual(result.lineage_node_count, 4)
            self.assertGreater(len(calls), 0)
        finally:
            fixture.close()

    def test_hostile_report_construction_never_authorizes_execution(self) -> None:
        class HostileReport(VersionedSelectedHistoryReportV1):
            def __eq__(self, _other: object) -> bool:
                return True

        fixture = VersionedHistoryTreeFixture()
        try:
            result = resolve_versioned_selected_history(str(fixture.authority))
            forged = dataclasses.replace(
                result,
                runtime_verified=True,
                execution_authorized=True,
                publication_authorized=True,
            )
            with self.assertRaises(VersionedSelectedHistoryError):
                require_versioned_history_execution_authorized(forged)
            hostile = HostileReport(*dataclasses.astuple(forged))
            with self.assertRaises(VersionedSelectedHistoryError):
                require_versioned_history_execution_authorized(hostile)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
