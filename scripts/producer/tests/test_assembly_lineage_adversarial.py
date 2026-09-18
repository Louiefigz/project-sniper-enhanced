from __future__ import annotations

import dataclasses
import json
import os
import unittest
from pathlib import Path
from types import MappingProxyType

from _assembly_lineage_fixture import AssemblyLineageFixture, build_current
from _common import pl  # noqa: F401
from headless.approved_parent_assembly_binding import (
    bind_approved_parent_assembly_receipt,
)
from headless.assembly_lineage_binding import (
    AssemblyLineageBindingError,
    bind_assembly_lineage_continuity,
)
from headless.generation_schema import parse_generation_commit
from headless.repair_intent import ParentRefV1


class AssemblyLineageAdversarialTests(unittest.TestCase):
    def _reject(
        self,
        fixture: AssemblyLineageFixture,
        historical: object = None,
        current: object = None,
    ) -> None:
        selected = current or fixture.current
        with self.assertRaises(AssemblyLineageBindingError):
            bind_assembly_lineage_continuity(
                historical or fixture.historical,
                selected.descriptor,
                selected.commit,
                selected.receipt,
            )

    def test_each_stale_continuity_role_fails_after_structural_binding(self) -> None:
        scenarios = (
            "parent-target",
            "parent-assembly",
            "base-media",
            "base-plan",
            "base-receipt",
            "timeline",
            "projection",
        )
        for scenario in scenarios:
            fixture = AssemblyLineageFixture(scenario)
            try:
                current = fixture.current
                bind_approved_parent_assembly_receipt(
                    current.descriptor, current.commit, current.receipt
                )
                with self.subTest(scenario=scenario):
                    self._reject(fixture)
            finally:
                fixture.close()

    def test_wrong_proof_scope_and_forged_lineage_fail(self) -> None:
        fixture = AssemblyLineageFixture()
        try:
            wrong_scope = dataclasses.replace(
                fixture.historical, proof_scope="global-publication-history"
            )
            self._reject(fixture, wrong_scope)
            reversed_lineage = dataclasses.replace(
                fixture.historical,
                lineage=tuple(reversed(fixture.historical.lineage)),
            )
            self._reject(fixture, reversed_lineage)
        finally:
            fixture.close()

    def test_separate_valid_child_cannot_borrow_selected_history(self) -> None:
        fixture = AssemblyLineageFixture()
        try:
            separate = build_current(fixture.historical, "projection")
            bind_approved_parent_assembly_receipt(
                separate.descriptor, separate.commit, separate.receipt
            )
            self._reject(fixture, current=separate)
        finally:
            fixture.close()

    def test_hostile_direct_parent_and_receipt_construction_fail(self) -> None:
        class HostileParent(ParentRefV1):
            def __eq__(self, other: object) -> bool:
                return True

        fixture = AssemblyLineageFixture()
        try:
            ref = fixture.historical.target.ref
            hostile = HostileParent(
                ref.authority_id,
                ref.publication_seq,
                ref.generation_id,
                ref.commit_digest,
                ref.plan_digest,
            )
            target = dataclasses.replace(fixture.historical.target, ref=hostile)
            forged = dataclasses.replace(fixture.historical, target=target)
            self._reject(fixture, forged)
            receipt = dataclasses.replace(
                fixture.current.receipt,
                parent_assembly_receipt_sha256="0" * 64,
            )
            current = dataclasses.replace(fixture.current, receipt=receipt)
            self._reject(fixture, current=current)
        finally:
            fixture.close()

    def test_materialized_ref_alias_and_inode_substitution_fail(self) -> None:
        fixture = AssemblyLineageFixture()
        try:
            descriptor = fixture.historical.target.descriptor
            paths = dict(fixture.historical.materialized)
            paths[descriptor.base.plan_artifact.relative_path] = paths[
                descriptor.base.timeline_map.relative_path
            ]
            aliased = dataclasses.replace(
                fixture.historical, materialized=MappingProxyType(paths)
            )
            self._reject(fixture, aliased)
            target = fixture.historical.materialized[
                descriptor.base.plan_artifact.relative_path
            ]
            replacement = fixture.authority.root / "replacement-base-plan"
            replacement.write_bytes(Path(target).read_bytes())
            replacement.chmod(0o600)
            os.replace(replacement, target)
            self._reject(fixture)
        finally:
            fixture.close()

    def test_genesis_current_commit_misuse_fails(self) -> None:
        fixture = AssemblyLineageFixture()
        try:
            document = json.loads(fixture.current.commit.document_json)
            document["expectedParent"] = None
            raw = json.dumps(
                document,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("ascii")
            commit = parse_generation_commit(raw)
            current = dataclasses.replace(fixture.current, commit=commit)
            self._reject(fixture, current=current)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
