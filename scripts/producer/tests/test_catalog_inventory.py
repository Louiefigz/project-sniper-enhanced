"""Complete catalog discovery is evidence, including unavailable sources."""
from __future__ import annotations

from argparse import Namespace
from unittest.mock import patch
import unittest

from _reference_reuse_fixture import ReuseFixture
from graphics.catalog_discovery import inventory_catalog
from graphics.catalog_discovery_cli import execute, render_text


class CatalogInventoryTests(ReuseFixture):
    """Exercise the real source reader without treating inert HTML as rendered."""

    def test_inventory_retains_every_item_and_current_source_identity(self) -> None:
        """No top-ten search window may hide the tail of a strategy inventory."""
        catalog = self.catalog()
        # Duplicate inert records under test-only identities to exceed search limits.
        original = catalog.records[0]
        catalog.records.extend({**original, "ref": f"mirror:test-{index}",
                                "id": f"test-{index}"} for index in range(120))
        result = inventory_catalog(catalog)
        self.assertEqual(result["total"], 122)
        self.assertEqual(result["returned"], result["total"])
        self.assertFalse(result["limited"])
        self.assertEqual(result["items"][-1]["ref"], "mirror:test-119")
        for row in result["items"]:
            self.assertEqual(len(row["source"]["sha256"]), 64)
            self.assertFalse(row["executionApproved"])

    def test_source_changes_change_inventory_without_claiming_qualification(self) -> None:
        """Saved candidate IDs cannot conceal a changed implementation."""
        before = inventory_catalog(self.catalog())
        (self.sources / "meter-card.html").write_text("<!-- TEST changed animation -->")
        after = inventory_catalog(self.catalog())
        self.assertNotEqual(before, after)
        self.assertTrue(all(not row["executionApproved"] for row in after["items"]))

    def test_missing_reference_is_visible_but_has_no_source_hash(self) -> None:
        """Incomplete media installs remain discoverable, never measured."""
        (self.sources / "meter-card.html").unlink()
        result = inventory_catalog(self.catalog())
        row = next(row for row in result["items"] if row["id"] == "meter-card")
        self.assertIsNone(row["source"]["sha256"])
        self.assertEqual(row["integration"]["status"], "reference-missing-source")

    def test_cli_and_text_read_the_same_complete_inventory(self) -> None:
        """The production CLI delegates to the shared catalog loader once."""
        with patch("graphics.catalog_discovery_cli.load_catalog", return_value=self.catalog()) as loader:
            result, code = execute(Namespace(command="inventory"))
        self.assertEqual(code, 0)
        loader.assert_called_once_with()
        text = render_text(result)
        self.assertIn("complete inventory: 2 items", text)
        self.assertIn("mirror:meter-card", text)


if __name__ == "__main__":
    unittest.main()
