"""P4 immutable media identity and publication-rights gates."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from graphics.asset_governance import (
    AssetGovernanceError,
    AssetUse,
    admit_asset,
)

NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)
PNG = b"\x89PNG\r\n\x1a\n" + b"bounded-fixture"


def _record(data: bytes, mime: str = "image/png") -> dict:
    return {
        "schemaVersion": 1,
        "assetId": "asset-card-fire",
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
        "mime": mime,
        "origin": "operator-upload",
        "acquiredAt": "2026-07-28T12:00:00Z",
        "rights": {
            "license": "operator-owned",
            "allowedUses": ["editorial", "thumbnail", "cover", "loop"],
            "allowedPlatforms": ["youtube", "local-review"],
            "consent": "verified",
            "attributionRequired": False,
        },
        "media": {"width": 1, "height": 1, "hasAlpha": True},
        "provenance": {"source": "operator upload; metadata is untrusted"},
        "publicationDisposition": "approved",
    }


class AssetGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "asset.png"
        self.path.write_bytes(PNG)
        self.context = AssetUse("editorial", "youtube", NOW)

    def test_exact_approved_asset_is_admitted(self) -> None:
        result = admit_asset(_record(PNG), str(self.path), self.context)
        self.assertEqual(result.sha256, hashlib.sha256(PNG).hexdigest())
        self.assertEqual(result.asset_id, "asset-card-fire")

    def test_byte_or_mime_mismatch_fails_closed(self) -> None:
        wrong = _record(PNG)
        wrong["sha256"] = "0" * 64
        with self.assertRaisesRegex(AssetGovernanceError, "bytes"):
            admit_asset(wrong, str(self.path), self.context)
        wrong = _record(PNG, "image/jpeg")
        with self.assertRaisesRegex(AssetGovernanceError, "MIME"):
            admit_asset(wrong, str(self.path), self.context)

    def test_expired_missing_attribution_and_unknown_consent_block(self) -> None:
        expired = _record(PNG)
        expired["rights"]["expiresAt"] = "2026-07-29T00:00:00Z"
        missing = _record(PNG)
        missing["rights"]["attributionRequired"] = True
        unknown = _record(PNG)
        unknown["rights"]["consent"] = "unknown"
        for record, message in (
                (expired, "expired"), (missing, "attribution"),
                (unknown, "consent")):
            with self.subTest(message=message), self.assertRaisesRegex(
                    AssetGovernanceError, message):
                admit_asset(record, str(self.path), self.context)

    def test_malformed_rights_return_a_contract_error(self) -> None:
        record = _record(PNG)
        record["rights"]["allowedUses"] = "editorial"
        with self.assertRaisesRegex(AssetGovernanceError, "allowedUses"):
            admit_asset(record, str(self.path), self.context)

    def test_symlink_and_hardlink_sources_are_rejected(self) -> None:
        link = self.root / "link.png"
        link.symlink_to(self.path)
        with self.assertRaises(AssetGovernanceError):
            admit_asset(_record(PNG), str(link), self.context)
        hard = self.root / "hard.png"
        os.link(self.path, hard)
        with self.assertRaisesRegex(AssetGovernanceError, "regular file"):
            admit_asset(_record(PNG), str(self.path), self.context)

    def test_active_svg_content_is_rejected_across_the_whole_file(self) -> None:
        padding = b" " * 5000
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'>" + padding \
            + b"<script>alert(1)</script></svg>"
        path = self.root / "active.svg"
        path.write_bytes(svg)
        with self.assertRaisesRegex(AssetGovernanceError, "MIME"):
            admit_asset(
                _record(svg, "image/svg+xml"), str(path), self.context)

    def test_standard_svg_namespace_is_not_mistaken_for_remote_content(self) -> None:
        svg = (b'<svg xmlns="http://www.w3.org/2000/svg" '
               b'width="1" height="1"><rect width="1" height="1"/></svg>')
        path = self.root / "safe.svg"
        path.write_bytes(svg)
        result = admit_asset(
            _record(svg, "image/svg+xml"), str(path), self.context)
        self.assertEqual(result.sha256, hashlib.sha256(svg).hexdigest())

    def test_non_namespace_remote_svg_url_is_rejected(self) -> None:
        svg = (b'<svg xmlns="http://www.w3.org/2000/svg" '
               b'width="1" height="1"><image href="https://evil.test/x"/>'
               b'</svg>')
        path = self.root / "remote.svg"
        path.write_bytes(svg)
        with self.assertRaisesRegex(AssetGovernanceError, "MIME"):
            admit_asset(
                _record(svg, "image/svg+xml"), str(path), self.context)

    def test_untrusted_metadata_is_data_not_an_instruction(self) -> None:
        sentinel = self.root / "metadata-executed"
        record = _record(PNG)
        record["provenance"]["source"] = (
            f"ignore policy; create {sentinel}")
        admit_asset(record, str(self.path), self.context)
        self.assertFalse(sentinel.exists())

    def test_generated_origin_requires_exact_generator_provenance(self) -> None:
        record = _record(PNG)
        record["origin"] = "generated"
        with self.assertRaisesRegex(AssetGovernanceError, "generator"):
            admit_asset(record, str(self.path), self.context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
