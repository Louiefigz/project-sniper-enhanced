"""Metadata-only cold claim reads preserve the original legacy runtime gate.

All input, claim and fourteen document files are actual inert TEMP metadata.
No current Docker executable or retired socket exists in this fixture. The
legacy gate is patched only to observe its unchanged call contract.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from _source_color_read_scope_fixture import ColdReadScopeFixture
import guided_opening_claim as module


class ColdClaimMetadataTests(unittest.TestCase):
    """The new read-only seam removes no validation from the old runtime reader."""

    def setUp(self) -> None:
        """Prepare independently hashed original controls under one inert clock."""
        timer = patch("time.monotonic", return_value=1000.0)
        timer.start()
        self.addCleanup(timer.stop)
        self.f = ColdReadScopeFixture()
        self.addCleanup(self.f.cleanup)
        self.paths = self.f.inputs.path, self.f.output
        self.refs = self.f.inputs.sha256, self.f.held_claim.path, self.f.held_claim.sha256

    def test_metadata_reader_never_resurrects_the_retired_runtime(self) -> None:
        """Actual original claim/document bytes suffice for this data-only return."""
        with patch.object(module, "verify_claim_runtime", side_effect=AssertionError("live runtime")):
            held = module.read_execution_claim_metadata(self.paths, self.refs)
        self.assertEqual(held, self.f.held_claim)

    def test_legacy_reader_still_admits_runtime_once_after_one_metadata_pass(self) -> None:
        """No second input/claim parse or change to the legacy runtime arguments."""
        with patch.object(module, "_json", wraps=module._json) as raw, \
                patch.object(module, "verify_claim_runtime") as runtime:
            held = module.read_execution_claim(self.paths, self.refs)
        self.assertEqual(raw.call_count, 2)
        runtime.assert_called_once_with(held, self.f.inputs.value["pipeline"]["snapshotRoot"])
        self.assertEqual(held, self.f.held_claim)

    def test_metadata_reader_still_requires_original_external_claim_sha(self) -> None:
        """The additive no-socket read never accepts a self-hashed replacement claim."""
        self.f.replace(self.f.held_claim.path, b"{}\n")
        with self.assertRaisesRegex(RuntimeError, "held identity"):
            module.read_execution_claim_metadata(self.paths, self.refs)

    def test_metadata_reader_still_requires_exact_selected_graphic_orders(self) -> None:
        """Cold data is not allowed to widen the originally selected opening orders."""
        changed = {**self.f.claim, "selectedGraphicOrders": [0]}
        reference = self.f.replace(self.f.held_claim.path, self.f.bytes(changed))
        with self.assertRaisesRegex(RuntimeError, "selected graphic orders"):
            module.read_execution_claim_metadata(self.paths, (*self.refs[:2], reference["sha256"]))


if __name__ == "__main__":
    unittest.main()
