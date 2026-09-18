"""Type-boundary attacks against streamed genesis structural binding."""

from __future__ import annotations

import dataclasses
import unittest
from collections.abc import ItemsView

from _common import pl  # noqa: F401
from _genesis_r1_fixture import genesis_r1_fixture
from _versioned_disk_fixture import VersionedDiskFixture
from headless.genesis_authority_validation import GenesisAuthorityBindingError
from headless.genesis_payload_reobservation import reobserve_genesis_payload
from headless.genesis_streaming_authority import bind_streamed_genesis_r1_authority
from headless.versioned_generation_reader import read_versioned_current_generation

_SEMANTIC_CLASSES = frozenset(
    {
        "genesis-approved-card-v2",
        "initialization-origin-receipt-v1",
        "headless-operation-v1",
        "initialization-snapshot-authority-v1",
        "initialization-execution-policy-v2",
        "generation-verification-v2",
        "repair-policy-v1",
        "quality-policy-v1",
        "fallback-policy-v1",
    }
)


class _HostileSemanticMapping(dict):
    def __init__(self, expected: dict[str, bytes]) -> None:
        super().__init__({key: b"forged" for key in expected})
        self._expected = expected

    def items(self) -> ItemsView[str, bytes]:
        return self._expected.items()

    def __getitem__(self, key: str) -> bytes:
        return self._expected[key]


class GenesisStreamingAuthorityAdversarialTests(unittest.TestCase):
    def test_hostile_mapping_cannot_change_values_between_checks(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        expected = {
            path: raw
            for path, raw in value.files.items()
            if value.classes[path] in _SEMANTIC_CLASSES
        }
        inputs = dataclasses.replace(
            value.inputs, artifact_bytes=_HostileSemanticMapping(expected)
        )
        try:
            with read_versioned_current_generation(
                str(fixture.authority), str(fixture.materialization)
            ) as selected:
                observation = reobserve_genesis_payload(selected)
            with self.assertRaises(GenesisAuthorityBindingError):
                bind_streamed_genesis_r1_authority(inputs, observation)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
