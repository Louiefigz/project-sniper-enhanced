#!/usr/bin/env python3
"""Selection and execution evidence for catalog candidates."""
from __future__ import annotations

from graphics.catalog_resource_index import unknown_resource_evidence

_ADAPTATION = ("inspect-current-source", "close-local-dependencies",
               "adapt-into-project-owned-native-composition",
               "guarded-capability-probe", "studio-session-lint")


def resource_evidence(record: dict, resources: dict[str, dict]) -> dict:
    """Join static evidence by upstream identity without inferring capability."""
    upstream = record.get("upstream") or {}
    name = upstream.get("name")
    if not name:
        return unknown_resource_evidence("no-upstream-resource-identity")
    return dict(resources.get(name) or unknown_resource_evidence(
        "resource-sidecar-row-unavailable"))


def eligibility(record: dict, resource: dict) -> dict:
    """Separate discovery eligibility from route-specific execution evidence."""
    status = record["integration"]["status"]
    source_exists = bool(record["source"]["exists"])
    prerequisites = _prerequisites(status, resource)
    execution = _execution_status(status, source_exists)
    return {"discoveryEligible": True,
            "selectionEligible": status != "reference-missing-source",
            "executionStatus": execution,
            "executionApproved": False,
            "prerequisites": prerequisites,
            "scope": "candidate-evidence-only; route gates still decide"}


def _prerequisites(status: str, resource: dict) -> list[str]:
    """Describe evidence work without approving route execution."""
    by_status = {
        "reference": _ADAPTATION,
        "reference-missing-source": ("restore-exact-pinned-source",),
        "integrated-unmeasured": ("refresh-measured-capability-artifact",),
    }
    prerequisites = list(by_status.get(status, ()))
    if resource.get("guardedProbeRequired") and "guarded-capability-probe" not in prerequisites:
        prerequisites.append("guarded-capability-probe")
    return prerequisites


def _execution_status(status: str, source_exists: bool) -> str:
    """Map catalog integration state to one closed execution state."""
    if status == "integrated-measured":
        return "measured-compatibility-candidate"
    if status == "reference" and source_exists:
        return "native-adaptation-required"
    if status == "reference-missing-source":
        return "blocked-missing-source"
    return "blocked-unmeasured-integration"
