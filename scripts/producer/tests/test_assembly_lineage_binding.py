from __future__ import annotations

import unittest

from _assembly_lineage_fixture import AssemblyLineageFixture
from _common import pl  # noqa: F401
from headless.assembly_lineage_binding import bind_assembly_lineage_continuity
from headless.assembly_lineage_types import (
    IMMEDIATE_EDGE_STATUS,
    IMMEDIATE_PARENT_AND_BASE_CONTINUITY,
    LINEAGE_PROOF_SCOPE,
    RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN,
)


class AssemblyLineageBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = AssemblyLineageFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_closes_only_immediate_parent_and_base_continuity(self) -> None:
        current = self.fixture.current
        result = bind_assembly_lineage_continuity(
            self.fixture.historical,
            current.descriptor,
            current.commit,
            current.receipt,
        )
        parent = self.fixture.historical.target.descriptor
        self.assertEqual(result.status, IMMEDIATE_EDGE_STATUS)
        self.assertEqual(result.proof_scope, LINEAGE_PROOF_SCOPE)
        self.assertEqual(
            result.closed_requirements, (IMMEDIATE_PARENT_AND_BASE_CONTINUITY,)
        )
        self.assertEqual(
            tuple(item.code for item in result.unresolved_authority),
            (RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN,),
        )
        self.assertEqual(result.parent, self.fixture.historical.target.ref)
        self.assertEqual(result.anchor_current, self.fixture.historical.anchor_current)
        self.assertEqual(result.selected_child, self.fixture.historical.lineage[0].ref)
        self.assertEqual(
            result.parent_assembly_receipt,
            parent.output.assembly_receipt,
        )
        self.assertEqual(result.base, parent.base.media)
        self.assertEqual(result.base_plan, parent.base.plan_artifact)
        self.assertEqual(result.base_receipt, parent.base.receipt)
        self.assertEqual(result.timeline_map, parent.base.timeline_map)
        self.assertEqual(
            result.base_projection_digest,
            parent.plan.base_projection_digest,
        )
        self.assertEqual(result.lineage_node_count, 3)
        self.assertEqual(result.assembly_edges_required, 2)
        self.assertEqual(result.assembly_edges_verified, 1)
        self.assertFalse(result.recursive_assembly_verified)
        self.assertFalse(result.genesis_origin_verified)
        self.assertFalse(result.runtime_verified)
        self.assertFalse(result.publication_authorized)


if __name__ == "__main__":
    unittest.main()
