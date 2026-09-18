"""Conservative sample summaries; global chroma never becomes white balance."""
from __future__ import annotations

from color.model import finite

FIELDS = ("yMin", "yP10", "yMedian", "yMean", "yP90", "yMax", "uMean", "vMean",
          "nominalBlackFraction", "nominalWhiteFraction")


def validate_sample(row: dict, requested: dict) -> None:
    """Bind actual source-time decode to one requested retained interval."""
    if row.get("id") != requested["id"] or row.get("requestedTime") != requested["sourceTime"]:
        raise ValueError("color worker sample identity differs from its request")
    if not finite(row.get("elapsedMs")) or row["elapsedMs"] < 0:
        raise ValueError("color worker sample elapsed timing is invalid")
    if row.get("status") != "sampled":
        if row.get("status") not in {"failed", "skipped"} or not row.get("error"):
            raise ValueError("color worker sample failure is malformed")
        return
    actual = row.get("actualSourceTime")
    expected_color = {"pixelFormat": "yuv420p", "range": "tv", "matrix": "bt709",
                      "primaries": "bt709", "transfer": "bt709", "hdrSignaled": False}
    if row.get("frameMetadata") != expected_color:
        raise ValueError("color worker sampled frame metadata is missing or unsupported")
    if not finite(actual) or not requested["sourceStart"] <= actual < requested["sourceEnd"] \
            or not -0.000001 <= actual - requested["sourceTime"] <= requested["maximumSeekDeltaS"]:
        raise ValueError("color worker sampled outside its retained source interval")
    stats = row.get("statistics")
    if type(stats) is not dict or set(stats) != set(FIELDS):
        raise ValueError("color worker statistics are incomplete")
    if any(not finite(stats[key]) or not 0 <= stats[key] <= 255 for key in FIELDS[:8]):
        raise ValueError("color worker statistics are out of range")
    if any(not finite(stats[key]) or not 0 <= stats[key] <= 1 for key in FIELDS[8:]):
        raise ValueError("color worker nominal-limit fractions are invalid")
    if not stats["yMin"] <= stats["yP10"] <= stats["yMedian"] <= stats["yP90"] <= stats["yMax"]:
        raise ValueError("color worker percentiles are inconsistent")
    if not stats["yMin"] <= stats["yMean"] <= stats["yMax"]:
        raise ValueError("color worker mean is inconsistent with its extrema")


def summarize(rows: list[dict]) -> dict:
    """Keep per-frame values and extrema; do not average away lighting changes."""
    complete = [row["statistics"] for row in rows if row["status"] == "sampled"]
    if not complete:
        return {"sampledFrames": 0}
    averages = {key: round(sum(row[key] for row in complete) / len(complete), 6) for key in FIELDS}
    return {"sampledFrames": len(complete), "means": averages,
            "minimumMeanLuma": min(row["yMean"] for row in complete),
            "maximumMeanLuma": max(row["yMean"] for row in complete),
            "worstNominalBlackFraction": max(row["nominalBlackFraction"] for row in complete),
            "worstNominalWhiteFraction": max(row["nominalWhiteFraction"] for row in complete),
            "measurementSpace": "area-downsampled encoded 8-bit limited-range YUV, not linear light",
            "clippingCaveat": "nominal-limit occupancy on sampled reduced frames; not proof of lost sensor detail"}


def review_suggestion(group: dict, metadata: dict, summary: dict) -> tuple[list[dict], list[str]]:
    """Offer bounded luma-screening candidates only with explicitly neutral context."""
    warnings = ["No temperature/tint adjustment: frame-average chroma is not a neutral reference."]
    declared = group["context"]
    if group["intent"] != "neutral":
        warnings.append(f"Lighting intent is {group['intent']}; dark or colored scenes may be intentional. No correction suggested.")
    if group["unsampledIntervalIndices"]:
        warnings.append("Some retained intervals were not sampled; inspect those shots before choosing a group correction.")
    if summary["sampledFrames"] == 0:
        return [], warnings
    means = summary["means"]
    spread = (summary["maximumMeanLuma"] - summary["minimumMeanLuma"]) / 219
    chroma = max(abs(means["uMean"] - 128), abs(means["vMean"] - 128))
    if spread > 0.18:
        warnings.append("Large within-group brightness variation; split or review lighting groups before correction.")
    if chroma > 18:
        warnings.append("Strong mean chroma may reflect scene content or colored lighting, not a white-balance error.")
    complete = summary["sampledFrames"] == len(group["samples"])
    eligible = (metadata["supportedSamplingClass"] and declared["sourceProfile"] == "bt709-sdr"
                and declared["cameraProfile"] is None and declared["historyState"] == "known"
                and not declared["transformHistory"] and group["intent"] == "neutral"
                and not group["unsampledIntervalIndices"] and complete and spread <= 0.18 and chroma <= 18)
    if not eligible:
        return [], warnings
    normalized = (means["yMean"] - 16) / 219
    delta = min(0.04, max(-0.04, (0.32 - normalized) * 0.2)) if normalized < 0.28 else 0
    if normalized > 0.72:
        delta = max(-0.04, (0.68 - normalized) * 0.2)
    if delta == 0:
        return [], warnings
    warnings.append("Brightness candidate is heuristic encoded-luma screening, not exposure stops or a renderer-ready grade; compare before use.")
    return [{"kind": "review-normalized-luma-offset", "value": round(delta, 4),
             "maximumAbsoluteValue": 0.04, "confidence": "screening-only",
             "applicableToPlan": False, "requiresOperatorComparison": True}], warnings
