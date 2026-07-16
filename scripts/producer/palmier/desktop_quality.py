"""Shared quality contract for governed Desktop Palmier worklists."""

from palmier.desktop_state import read_record
from palmier.native_qc_contract import stable_hash


def quality_contract() -> dict:
    """Return the operator-visible visual and editorial acceptance contract."""
    return {
        "readbackCadence": "after every risky/dependency-producing batch",
        "framing": "face must remain in the measured clear region at payoff",
        "typography": "consistent family/scale; no text-background camouflage",
        "contrast": {"normalTextMin": 4.5, "largeTextMin": 3.0},
        "graphics": "vary information anatomy; never repeat a form when a compatible form fits",
        "faceBridge": {
            "authority": "copy the plan's informationForm→kind→chassis tuple exactly",
            "cream": "left rail with measured presenter-safe right-side footage",
            "dark": "own-screen canvas with the registered persistent right presenter hole",
            "forbidden": "generic lower-third, payoff, or glass fallback",
        },
        "transitions": "use only earned, supported seam punctuation; hard cuts need rationale",
        "color": ("inspect exposure, contrast, saturation, temperature, "
                  "skin tone, and shot matching"),
        "final": "exact candidate export + deterministic Audit B + composition/editorial reviews",
    }


def qc_authority(state: dict) -> dict:
    """Bind final QC to the effective plan plus any Desktop-only revision."""
    authority = {"inputDigest": stable_hash(state),
                 "editPlan": read_record(state["plan"]["path"], "plan")}
    revision = state.get("revision")
    if isinstance(revision, dict):
        authority["revisionSet"] = read_record(revision["path"], "revision")
    return authority
