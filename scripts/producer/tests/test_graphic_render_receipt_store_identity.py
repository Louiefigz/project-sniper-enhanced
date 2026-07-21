"""Identity and R0 policy tests for retained graphic receipt sets."""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _graphic_render_receipt_store_fixture import (
    graphic_receipt_store_fixture,
)
from headless import graphic_render_receipt_store_io as store_io
from headless.graphic_render_receipt_semantics import (
    parse_graphic_render_receipt_v1,
)
from headless.graphic_render_receipt_store import (
    store_graphic_render_receipt_set,
    try_load_graphic_render_receipt_set,
)
from headless.graphic_render_receipt_store_types import (
    GraphicRenderReceiptStoreError,
)


class GraphicRenderReceiptStoreIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = graphic_receipt_store_fixture(self.root)

    def _store(self) -> None:
        store_graphic_render_receipt_set(
            self.fixture.attempt_root,
            self.fixture.expectation,
            (self.fixture.receipt,),
        )

    def _final(self) -> Path:
        return (
            Path(self.fixture.attempt_root)
            / "work"
            / store_io.STORE_NAME
            / store_io.FINAL_NAME
        )

    def test_existing_final_rejects_different_valid_receipt_bytes(
        self,
    ) -> None:
        self._store()
        document = json.loads(self.fixture.receipt.document_json)
        digest = "9" * 64
        document["media"]["artifact"]["sha256"] = digest
        document["renderArtifactDigest"] = digest
        forged = parse_graphic_render_receipt_v1(canonical(document))
        with self.assertRaisesRegex(
            GraphicRenderReceiptStoreError, "replay bytes conflict"
        ):
            store_graphic_render_receipt_set(
                self.fixture.attempt_root,
                self.fixture.expectation,
                (forged,),
            )

    def test_r0_rejects_multi_graphic_sets_before_any_store_write(
        self,
    ) -> None:
        second = dataclasses.replace(
            self.fixture.expectation.receipts[0],
            ordinal=1,
            graphic_id="g-00000002",
        )
        expectation = dataclasses.replace(
            self.fixture.expectation,
            receipts=(self.fixture.expectation.receipts[0], second),
        )
        with self.assertRaises(GraphicRenderReceiptStoreError):
            store_graphic_render_receipt_set(
                self.fixture.attempt_root,
                expectation,
                (self.fixture.receipt, self.fixture.receipt),
            )
        self.assertFalse(
            (Path(self.fixture.attempt_root) / store_io.LOCK_NAME).exists()
        )

    def test_copying_a_set_to_another_attempt_rejects_attempt_binding(
        self,
    ) -> None:
        self._store()
        target_root = self.root / "target"
        target_root.mkdir(mode=0o700)
        target = graphic_receipt_store_fixture(target_root)
        target_expectation = dataclasses.replace(
            target.expectation,
            attempt_id="33333333-3333-4333-8333-333333333333",
            admission_artifact_digest=(
                self.fixture.expectation.admission_artifact_digest
            ),
            request_digest=self.fixture.expectation.request_digest,
            quality_policy_id=self.fixture.expectation.quality_policy_id,
            render_build_digest=self.fixture.expectation.render_build_digest,
            runtime_image_id=self.fixture.expectation.runtime_image_id,
            proof_ffmpeg_sha256=(self.fixture.expectation.proof_ffmpeg_sha256),
            proof_ffprobe_sha256=(
                self.fixture.expectation.proof_ffprobe_sha256
            ),
            receipts=self.fixture.expectation.receipts,
        )
        source_store = self._final().parent
        destination = Path(target.attempt_root) / "work" / store_io.STORE_NAME
        shutil.copytree(source_store, destination)
        lock = Path(target.attempt_root) / store_io.LOCK_NAME
        lock.write_bytes(b"")
        lock.chmod(0o600)
        with self.assertRaisesRegex(
            GraphicRenderReceiptStoreError, "identity is stale"
        ):
            try_load_graphic_render_receipt_set(
                target.attempt_root, target_expectation
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
