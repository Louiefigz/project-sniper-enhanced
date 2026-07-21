"""Trusted deterministic transforms applied to live composition source."""
from __future__ import annotations

import math
import re

_ROOT_TAG = re.compile(r'<[^>]*data-composition-id="[^"]*"[^>]*>')
_DURATION = re.compile(r'data-duration="[^"]*"')


def set_root_duration(html: str, duration: float) -> str:
    """Rewrite only the composition root's finite positive duration."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("composition duration must be finite and positive")

    def rewrite(match: re.Match) -> str:
        tag, count = _DURATION.subn(
            f'data-duration="{duration:g}"', match.group(0), count=1)
        if count != 1:
            raise ValueError("composition root tag has no data-duration attribute")
        return tag

    transformed, count = _ROOT_TAG.subn(rewrite, html, count=1)
    if count != 1:
        raise ValueError("composition has no data-composition-id root element")
    return transformed
