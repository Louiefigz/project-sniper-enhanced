"""Private-root fixture for standalone active-fence tests."""

from __future__ import annotations

import os
import tempfile
import uuid

from _common import pl  # noqa: F401
from headless.active_fence_materialized import ACTIVE_FENCE_NAME
from headless.active_fence_protocol import (
    bootstrap_active_generation_fence_v1,
    cancel_active_generation_fence_v1,
    reserve_active_generation_fence_v1,
)


class ActiveFenceFixture:
    """Own one canonical mode-0700 authority root."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(
            os.path.join(self.temporary.name, "authority")
        )
        os.mkdir(self.root, 0o700)
        os.chmod(self.root, 0o700)
        self.authority_id = "authority-mp4-v1"
        self.attempt_a = str(uuid.uuid4())
        self.attempt_b = str(uuid.uuid4())

    def close(self) -> None:
        """Remove the temporary authority root."""
        self.temporary.cleanup()

    @property
    def journal_path(self) -> str:
        """Return the transition-journal path."""
        return os.path.join(self.root, "active-fence-transitions-v1.jsonl")

    @property
    def fence_path(self) -> str:
        """Return the materialized FENCE path."""
        return os.path.join(self.root, ACTIVE_FENCE_NAME)

    @property
    def lock_path(self) -> str:
        """Return the never-unlinked mutex path."""
        return os.path.join(self.root, ".publish.mutex")

    def journal_bytes(self) -> bytes:
        """Read raw test-owned journal bytes."""
        with open(self.journal_path, "rb") as source:
            return source.read()

    def fence_bytes(self) -> bytes:
        """Read raw test-owned materialized bytes."""
        with open(self.fence_path, "rb") as source:
            return source.read()

    def bootstrap(self):
        """Bootstrap this fixture authority."""
        return bootstrap_active_generation_fence_v1(
            self.root, self.authority_id
        )

    def reserve(self, attempt_id: str | None = None):
        """Reserve the selected fixture attempt."""
        return reserve_active_generation_fence_v1(
            self.root, self.authority_id, attempt_id or self.attempt_a
        )

    def cancel(self, attempt_id: str | None = None):
        """Cancel the selected fixture attempt."""
        return cancel_active_generation_fence_v1(
            self.root, self.authority_id, attempt_id or self.attempt_a
        )
