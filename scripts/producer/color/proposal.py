"""Review-only group proposals with exact worker/sample bindings and caveats."""
from __future__ import annotations

from color.metadata import context_warnings, source_metadata
from color.statistics import review_suggestion, summarize, validate_sample


def group_proposal(group: dict, envelope: dict) -> dict:
    """Never mistake unsupported metadata or a partial worker result for quality."""
    worker = envelope["worker"]
    metadata = source_metadata(worker["probe"])
    wanted = {row["id"]: row for row in group["samples"]}
    all_rows = worker.get("samples") or []
    rows = [row for row in all_rows if row.get("id") in wanted]
    if len(rows) != len(wanted) or {row["id"] for row in rows} != set(wanted):
        raise ValueError("color worker did not account for every planned sample")
    for row in rows:
        validate_sample(row, wanted[row["id"]])
    summary = summarize(rows)
    suggestions, warnings = review_suggestion(group, metadata, summary)
    warnings = context_warnings(metadata, group["context"]) + warnings
    failures = [row for row in rows if row["status"] != "sampled"]
    if failures:
        warnings.append("Sampling was incomplete; failed/skipped attempts and timings are retained.")
    return {**group, "metadata": metadata, "observations": rows, "summary": summary,
            "suggestions": suggestions, "warnings": warnings,
            "reviewState": "unreviewed", "deliveryApproved": False,
            "qualityQualified": False, "writesGrade": False}
