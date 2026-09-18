#!/usr/bin/env python3
"""gate_policy — the typed verdict vocabulary new detectors declare through.

The minimal kernel of the QUALITY_MINING_REPORT gate-policy layer (Plan-Time
Geometry Contract v3, build item #1). New detectors (feasibility lint,
comp-size measurement, face-aware placement lints) express findings as
:class:`Verdict` records instead of ad-hoc print statements, and a registered
policy table decides what each verdict EFFECTIVELY does for a given target:

* ``FAIL`` — the detector observed a blocking defect.
* ``WARN`` — advisory; the plan still renders.
* ``SKIP`` — the check could not run. SKIP is legal ONLY with a non-empty
  evidence string: an unavailable capability must say why (never silent).

The policy table maps ``(gate, mode, lane)`` to an effective severity CAP.
A cap can DEMOTE (a FAIL verdict under a WARN cap merely advises — the A3
"WARN until calibrated" discipline) or declare a gate out of force for a
(mode, lane) via a SKIP cap. A cap never promotes: a detector's WARN stays
advisory. Resolution is fail-closed — an unregistered gate, an unknown
mode/lane, or a verdict/target mode disagreement RAISES loudly.

``to_gate_json`` adapts a verdict list to the existing gate CLI contract
(``{ok, errors, warnings}``) so existing consumers (planning-gates.ts
``parsePlanningGateVerdict``) work unchanged.

This module does NOT rewire existing gates; they keep their Report shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from edit_scope import LANES
from producer_config import MODES

SEVERITIES = ("FAIL", "WARN", "SKIP")
ACTIONS = ("block", "advise", "skip")
# Only these may be a gate's registered DEFAULT (a default of SKIP would make
# the gate permanently dark, which contradicts registering it at all).
_DEFAULT_SEVERITIES = ("FAIL", "WARN")
_VERDICT_FIELDS = ("gate", "severity", "evidence", "lane", "mode")
_REQUIRED_FIELDS = ("gate", "severity", "evidence")


class GatePolicyError(ValueError):
    """A malformed verdict, policy registration, or resolution input."""


def _require_gate_name(gate: object) -> None:
    """Raise unless ``gate`` is a non-empty string."""
    if not isinstance(gate, str) or not gate.strip():
        raise GatePolicyError(f"gate must be a non-empty string, got {gate!r}")


@dataclass(frozen=True)
class Verdict:
    """One typed finding a detector declares through the gate-policy layer.

    Attributes:
        gate: The declaring gate's identifier (e.g. ``"geometry_feasibility"``).
        severity: ``"FAIL"`` | ``"WARN"`` | ``"SKIP"``.
        evidence: Human-readable finding text. Always required non-empty; for
            SKIP it must say WHY the check could not run.
        lane: Optional lane the finding pertains to (``edit_scope.LANES``).
        mode: Optional mode the finding pertains to (``producer_config.MODES``).
    """

    gate: str
    severity: str
    evidence: str
    lane: Optional[str] = None
    mode: Optional[str] = None

    def __post_init__(self) -> None:
        """Strictly validate every field; raise on any malformed value.

        Raises:
            GatePolicyError: On an empty gate, unknown severity, empty
                evidence (SKIP-with-evidence discipline), or a lane/mode
                outside the registered vocabularies.
        """
        _require_gate_name(self.gate)
        if self.severity not in SEVERITIES:
            raise GatePolicyError(
                f"[{self.gate}] severity {self.severity!r} — one of {list(SEVERITIES)}")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            if self.severity == "SKIP":
                raise GatePolicyError(
                    f"[{self.gate}] SKIP without evidence — an unavailable "
                    "capability must say why")
            raise GatePolicyError(
                f"[{self.gate}] {self.severity} verdict requires non-empty evidence")
        if self.lane is not None and self.lane not in LANES:
            raise GatePolicyError(
                f"[{self.gate}] unknown lane {self.lane!r} — one of "
                f"{sorted(LANES)} or None")
        if self.mode is not None and self.mode not in MODES:
            raise GatePolicyError(
                f"[{self.gate}] unknown mode {self.mode!r} — one of "
                f"{sorted(MODES)} or None")

    def to_dict(self) -> dict:
        """JSON-safe dict of every field (transport across process seams).

        Returns:
            ``{"gate", "severity", "evidence", "lane", "mode"}``.
        """
        return {"gate": self.gate, "severity": self.severity,
                "evidence": self.evidence, "lane": self.lane, "mode": self.mode}


def verdict_from_dict(data: object) -> Verdict:
    """Rebuild a :class:`Verdict` from :meth:`Verdict.to_dict` output.

    Strict transport: unknown or missing fields RAISE instead of being
    dropped/defaulted (fail-closed — a shape drift must surface loudly).
    """
    if not isinstance(data, dict):
        raise GatePolicyError(f"verdict payload must be a dict, got {type(data).__name__}")
    unknown = sorted(set(data) - set(_VERDICT_FIELDS))
    if unknown:
        raise GatePolicyError(f"unknown verdict fields {unknown}")
    missing = sorted(set(_REQUIRED_FIELDS) - set(data))
    if missing:
        raise GatePolicyError(f"verdict payload missing required fields {missing}")
    return Verdict(gate=data["gate"], severity=data["severity"],
                   evidence=data["evidence"], lane=data.get("lane"),
                   mode=data.get("mode"))


def _validate_overrides(gate: str, overrides: dict) -> dict:
    """Validate a ``{(mode|None, lane|None): severity}`` override table for
    one gate; returns a defensive copy. Raises on a non-tuple key, an
    all-``None`` key (that is the default's job), or unknown values.
    """
    out: dict = {}
    for key, sev in overrides.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise GatePolicyError(f"[{gate}] override key {key!r} must be (mode, lane)")
        mode, lane = key
        if mode is None and lane is None:
            raise GatePolicyError(
                f"[{gate}] override (None, None) is illegal — use the default")
        if mode is not None and mode not in MODES:
            raise GatePolicyError(f"[{gate}] override mode {mode!r} — one of {sorted(MODES)}")
        if lane is not None and lane not in LANES:
            raise GatePolicyError(f"[{gate}] override lane {lane!r} — one of {sorted(LANES)}")
        if sev not in SEVERITIES:
            raise GatePolicyError(
                f"[{gate}] override severity {sev!r} — one of {list(SEVERITIES)}")
        out[(mode, lane)] = sev
    return out


def _target_mode(verdict: Verdict, target: Optional[dict]) -> Optional[str]:
    """The mode a verdict resolves under: verdict-declared, else target's
    (``None`` when neither declares one). Raises on an unknown target mode
    or a verdict/target mode disagreement (a detector bug — never silently
    pick one).
    """
    declared = verdict.mode
    t_mode = (target or {}).get("mode")
    if t_mode is not None and t_mode not in MODES:
        raise GatePolicyError(f"unknown target mode {t_mode!r} — one of {sorted(MODES)}")
    if declared is not None and t_mode is not None and declared != t_mode:
        raise GatePolicyError(
            f"[{verdict.gate}] verdict mode {declared!r} disagrees with "
            f"target mode {t_mode!r}")
    return declared if declared is not None else t_mode


class GatePolicy:
    """The policy table: per-gate registered defaults + (mode, lane) caps."""

    def __init__(self) -> None:
        self._table: dict = {}

    def register(self, gate: str, default: str,
                 overrides: Optional[dict] = None) -> None:
        """Register a gate's default severity and optional per-target caps.

        Idempotent for an IDENTICAL re-registration (double import is safe);
        a CONFLICTING re-registration raises.

        ``default`` is ``"FAIL"`` or ``"WARN"`` (a SKIP default is
        illegal); ``overrides`` caps are ``{(mode|None, lane|None):
        severity}``, more-specific keys winning.
        """
        _require_gate_name(gate)
        if default not in _DEFAULT_SEVERITIES:
            raise GatePolicyError(
                f"[{gate}] default severity {default!r} — one of {list(_DEFAULT_SEVERITIES)}")
        entry = {"default": default,
                 "overrides": _validate_overrides(gate, overrides or {})}
        existing = self._table.get(gate)
        if existing is not None and existing != entry:
            raise GatePolicyError(
                f"gate {gate!r} already registered with a different policy")
        self._table[gate] = entry

    def effective_severity(self, gate: str, mode: Optional[str],
                           lane: Optional[str]) -> str:
        """The severity cap in force for ``(gate, mode, lane)``.

        Precedence: exact ``(mode, lane)`` > ``(mode, None)`` >
        ``(None, lane)`` > the gate's registered default. An unregistered
        gate RAISES (fail-closed — never silently advise).
        """
        entry = self._table.get(gate)
        if entry is None:
            raise GatePolicyError(
                f"gate {gate!r} is not registered — register_gate() its "
                "default before resolving (fail-closed)")
        overrides = entry["overrides"]
        for key in ((mode, lane), (mode, None), (None, lane)):
            if key in overrides:
                return overrides[key]
        return entry["default"]

    def resolve(self, verdict: Verdict, target: Optional[dict] = None) -> str:
        """What one verdict effectively does for this target.

        The cap is a CEILING, never a promoter: a FAIL verdict under a WARN
        cap advises; a WARN verdict never blocks; a SKIP on either side skips.

        Returns ``"block"`` | ``"advise"`` | ``"skip"``; raises on an
        unregistered gate, unknown target mode, or mode disagreement.
        """
        mode = _target_mode(verdict, target)
        cap = self.effective_severity(verdict.gate, mode, verdict.lane)
        if verdict.severity == "SKIP" or cap == "SKIP":
            return "skip"
        if verdict.severity == "FAIL" and cap == "FAIL":
            return "block"
        return "advise"


#: The process-wide policy table detectors register into at import time.
POLICY = GatePolicy()


def register_gate(gate: str, default: str,
                  overrides: Optional[dict] = None) -> None:
    """Register a gate on the process-wide :data:`POLICY` table.

    Args:
        gate: Gate identifier.
        default: ``"FAIL"`` or ``"WARN"``.
        overrides: Optional ``{(mode|None, lane|None): severity}`` caps.
    """
    POLICY.register(gate, default, overrides)


def resolve(verdict: Verdict, target: Optional[dict] = None) -> str:
    """Resolve one verdict against the process-wide :data:`POLICY` table.

    Args:
        verdict: The declared verdict.
        target: The plan's ``target`` dict; optional.

    Returns:
        ``"block"`` | ``"advise"`` | ``"skip"``.
    """
    return POLICY.resolve(verdict, target)


def severity_for(gate: str, default: str, calibrated: bool) -> str:
    """Calibration flag: "WARN until calibrated, FAIL after" (contract A3).

    A detector whose blocking threshold has no empirical residual ledger yet
    declares its verdicts at ``severity_for(gate, "FAIL", calibrated=False)``
    → WARN; once the calibration loop (build item #4) proves the margin, the
    same call with ``calibrated=True`` returns the registered default.

    Returns ``default`` when calibrated, else ``"WARN"``; raises on a bad
    gate name or a default outside FAIL/WARN.
    """
    _require_gate_name(gate)
    if default not in _DEFAULT_SEVERITIES:
        raise GatePolicyError(
            f"[{gate}] calibration default {default!r} — one of {list(_DEFAULT_SEVERITIES)}")
    return default if calibrated else "WARN"


def _finding(verdict: Verdict, action: str) -> str:
    """The gate-attributed finding string; skips are labeled (never
    silent), a policy-driven skip distinct from a declared SKIP.
    """
    if action in ("block", "advise"):
        return f"{verdict.gate}: {verdict.evidence}"
    if verdict.severity == "SKIP":
        return f"{verdict.gate}: SKIP — {verdict.evidence}"
    return f"{verdict.gate}: SKIP (policy) — {verdict.evidence}"


def to_gate_json(verdicts: list, target: Optional[dict] = None,
                 policy: Optional[GatePolicy] = None) -> dict:
    """Adapt verdicts to the existing gate CLI contract: ``{ok, errors, warnings}``.

    Blocked verdicts land in ``errors``; advisories AND labeled skips land in
    ``warnings`` (a skip is visible-with-evidence, never blocking, never
    silent). ``ok`` is true iff nothing blocked — exactly the shape
    planning-gates.ts ``parsePlanningGateVerdict`` accepts unchanged. A gate
    CLI prints ``json.dumps(to_gate_json(...))`` and exits ``0 if ok else 1``.

    Args:
        verdicts: The detector's :class:`Verdict` list (may be empty).
        target: The plan's ``target`` dict for mode context; optional.
        policy: Policy table to resolve against (default: :data:`POLICY`).

    Returns:
        ``{"ok": bool, "errors": [str], "warnings": [str]}``.

    Raises:
        GatePolicyError: Propagated from resolution (unregistered gate,
            mode disagreement, unknown target mode).
    """
    table = policy if policy is not None else POLICY
    errors: list = []
    warnings: list = []
    for verdict in verdicts:
        action = table.resolve(verdict, target)
        bucket = errors if action == "block" else warnings
        bucket.append(_finding(verdict, action))
    return {"ok": not errors, "errors": errors, "warnings": warnings}
