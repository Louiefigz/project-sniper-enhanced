"""Path-free evidence summaries and resource clocks for the P5 cohort."""
from __future__ import annotations

import resource
import sys


def identity(value: dict) -> dict:
    """Retain stable media identity fields without temporary paths."""
    return {
        key: value[key]
        for key in ("sha256", "sizeBytes", "mtimeNs")
        if key in value
    }


def receipt_summary(value: dict) -> dict:
    """Project one full repair receipt into retained path-free evidence."""
    delta = value["bindingDelta"]
    return {
        "receiptHash": value["receiptHash"],
        "projectFanout": value["projectFanout"],
        "unitWork": value["unitWork"],
        "execution": value["execution"],
        "promotion": value["promotion"],
        "baseUnchanged": value["baseBefore"] == value["baseAfter"],
        "baseIdentity": identity(value["baseBefore"]),
        "reviewIdentity": identity(value["reviewMedia"]["output"]),
        "channelNormalization": value["reviewMedia"]["channelNormalization"],
        "decode": value["reviewMedia"]["decode"],
        "bindingDelta": {
            "actions": [row["action"] for row in delta["operations"]],
            "bindingIds": [
                row["bindingId"] for row in delta["operations"]
            ],
            "preserved": delta["preservedBindingIds"],
        },
        "implementation": value["implementation"],
    }


def resource_snapshot() -> dict:
    """Read process/child CPU and normalized maximum resident bytes."""
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    scale = 1 if sys.platform == "darwin" else 1024
    return {
        "processUserCpuSeconds": own.ru_utime,
        "processSystemCpuSeconds": own.ru_stime,
        "childUserCpuSeconds": child.ru_utime,
        "childSystemCpuSeconds": child.ru_stime,
        "processMaxRssBytes": int(own.ru_maxrss * scale),
        "childMaxRssBytes": int(child.ru_maxrss * scale),
    }


def resource_delta(before: dict, after: dict) -> dict:
    """Return CPU deltas and final maximum RSS observations."""
    cpu = [
        "processUserCpuSeconds", "processSystemCpuSeconds",
        "childUserCpuSeconds", "childSystemCpuSeconds",
    ]
    result = {
        key: round(after[key] - before[key], 6)
        for key in cpu
    }
    result.update({
        key: after[key]
        for key in ("processMaxRssBytes", "childMaxRssBytes")
    })
    return result
