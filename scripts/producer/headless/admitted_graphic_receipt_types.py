"""Controller-only authority for retained admitted graphic receipts."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIGEST = re.compile(r"[0-9a-f]{64}")


class AdmittedGraphicRenderReceiptError(RuntimeError):
    """An admitted lane cannot produce or reopen its exact receipt set."""


@dataclass(frozen=True)
class GraphicRenderReceiptControllerAuthorityV1:
    """Outer identities that cannot be inferred from render admission."""

    request_digest: str
    quality_policy_id: str


def validate_controller_authority(
    value: object,
) -> GraphicRenderReceiptControllerAuthorityV1:
    """Require exact immutable outer request and quality-policy digests."""
    valid = type(value) is GraphicRenderReceiptControllerAuthorityV1
    if valid:
        values = (value.request_digest, value.quality_policy_id)
        valid = all(
            type(item) is str and bool(_DIGEST.fullmatch(item))
            for item in values
        )
        valid = valid and value.request_digest != value.quality_policy_id
    if not valid:
        raise AdmittedGraphicRenderReceiptError(
            "graphic receipt controller authority is invalid"
        )
    return value
