"""Release matrix for continuous tracking and animated presenter PIP."""
from __future__ import annotations

_FIXTURES = {
    "no-face", "multiple-face", "face-exit", "occluded-face",
    "screen-share", "shot-boundary", "fast-motion", "safe-zone",
    "canvas-9x16-30000x1001", "canvas-16x9-24", "manual-override",
}


def advanced_motion_release_status(value: object) -> dict:
    """Return a fail-closed release verdict from the exact required matrix."""
    if not isinstance(value, list):
        raise ValueError("advanced-motion evidence must be an array")
    rows: dict[str, bool] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {
                "fixtureId", "trackingPassed", "animatedPipPassed"}:
            raise ValueError(
                f"advanced-motion fixture {index} has invalid fields")
        fixture = item["fixtureId"]
        if fixture not in _FIXTURES or fixture in rows:
            raise ValueError(
                f"advanced-motion fixture {index} is unknown or duplicate")
        states = item["trackingPassed"], item["animatedPipPassed"]
        if not all(type(state) is bool for state in states):
            raise ValueError(
                f"advanced-motion fixture {index} verdicts must be boolean")
        rows[fixture] = all(states)
    missing = sorted(_FIXTURES - set(rows))
    failed = sorted(key for key, passed in rows.items() if not passed)
    released = not missing and not failed
    return {
        "released": released, "missingFixtures": missing,
        "failedFixtures": failed, "requiredFixtureCount": len(_FIXTURES),
    }


def reject_unreleased_advanced_motion(plan: dict, rep: object) -> None:
    """Reject advanced fields; no runtime release evidence is wired to plans."""
    reframe = plan.get("reframe") or {}
    tracking = (reframe.get("continuousTracking")
                if isinstance(reframe, dict) else None)
    if tracking is not None and tracking is not False:
        rep.error(
            "reframe.continuousTracking is unsupported: the required "
            "tracking/PIP fixture matrix has not passed")
    presenter = plan.get("presenter") or {}
    if not isinstance(presenter, dict):
        rep.error("presenter must be an object")
        return
    animated = presenter.get("animatedPip")
    if animated is not None and animated is not False:
        rep.error(
            "presenter.animatedPip is unsupported: the required "
            "tracking/PIP fixture matrix has not passed")
