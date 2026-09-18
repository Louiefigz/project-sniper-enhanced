"""gate_policy tests — the typed verdict vocabulary + policy resolution.

Covers the four contract surfaces of the gate-policy kernel (Plan-Time
Geometry Contract v3, build item #1):

* Verdict schema — strict field validation against the registered mode/lane
  vocabularies, frozen record, strict dict transport round-trip.
* SKIP-with-evidence — a SKIP (and every other severity) is illegal without
  a non-empty evidence string.
* Policy resolution — per-gate defaults, (mode, lane) cap precedence, caps
  demote but never promote, fail-closed on unregistered gates and mode
  disagreements, idempotent-vs-conflicting registration.
* to_gate_json adapter — output matches the exact {ok, errors, warnings}
  contract planning-gates.ts parsePlanningGateVerdict enforces.
"""
import json
import unittest
from dataclasses import FrozenInstanceError

from _common import *  # noqa: F401,F403
import edit_scope as es
import gate_policy as gpol
from producer_config import MODES


def _v(gate: str = "geometry_feasibility", severity: str = "FAIL",
       evidence: str = "no legal region under punch 1.12",
       lane: str | None = "graphics", mode: str | None = "short") -> gpol.Verdict:
    """A valid verdict; each test overrides only the field it targets."""
    return gpol.Verdict(gate=gate, severity=severity, evidence=evidence,
                        lane=lane, mode=mode)


class VerdictSchemaTests(unittest.TestCase):
    """Verdict: strict validation, frozen record, strict dict transport."""

    def test_valid_verdict_constructs(self) -> None:
        v = _v()
        self.assertEqual(v.gate, "geometry_feasibility")
        self.assertEqual(v.severity, "FAIL")
        self.assertEqual(v.lane, "graphics")
        self.assertEqual(v.mode, "short")

    def test_lane_and_mode_default_to_none(self) -> None:
        v = gpol.Verdict(gate="g", severity="WARN", evidence="x")
        self.assertIsNone(v.lane)
        self.assertIsNone(v.mode)

    def test_bad_severity_rejected(self) -> None:
        for bad in ("fail", "ERROR", "", None, 1):
            with self.assertRaises(gpol.GatePolicyError):
                _v(severity=bad)

    def test_bad_gate_rejected(self) -> None:
        for bad in ("", "   ", None, 7):
            with self.assertRaises(gpol.GatePolicyError):
                _v(gate=bad)

    def test_every_registered_lane_accepted(self) -> None:
        for lane in es.LANES:
            self.assertEqual(_v(lane=lane).lane, lane)

    def test_unknown_lane_rejected(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            _v(lane="music")

    def test_every_registered_mode_accepted(self) -> None:
        for mode in MODES:
            self.assertEqual(_v(mode=mode).mode, mode)

    def test_unknown_mode_rejected(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            _v(mode="long")

    def test_verdict_is_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            _v().severity = "WARN"

    def test_dict_round_trip(self) -> None:
        v = _v()
        self.assertEqual(gpol.verdict_from_dict(v.to_dict()), v)

    def test_dict_round_trip_survives_json(self) -> None:
        v = _v(lane=None, mode=None)
        self.assertEqual(gpol.verdict_from_dict(json.loads(json.dumps(v.to_dict()))), v)

    def test_from_dict_unknown_field_rejected(self) -> None:
        payload = _v().to_dict()
        payload["placement"] = [0, 0, 100, 100]  # solved state must never ride along
        with self.assertRaises(gpol.GatePolicyError):
            gpol.verdict_from_dict(payload)

    def test_from_dict_missing_required_field_rejected(self) -> None:
        payload = _v().to_dict()
        del payload["evidence"]
        with self.assertRaises(gpol.GatePolicyError):
            gpol.verdict_from_dict(payload)

    def test_from_dict_non_dict_rejected(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            gpol.verdict_from_dict([_v().to_dict()])


class SkipEvidenceTests(unittest.TestCase):
    """SKIP is legal ONLY with non-empty evidence; FAIL/WARN need it too."""

    def test_skip_without_evidence_rejected(self) -> None:
        for empty in ("", "   ", None):
            with self.assertRaises(gpol.GatePolicyError) as ctx:
                _v(severity="SKIP", evidence=empty)
            self.assertIn("SKIP without evidence", str(ctx.exception))

    def test_skip_with_evidence_legal(self) -> None:
        v = _v(severity="SKIP", evidence="no face samples in window — detector unavailable")
        self.assertEqual(v.severity, "SKIP")

    def test_fail_and_warn_also_require_evidence(self) -> None:
        for sev in ("FAIL", "WARN"):
            with self.assertRaises(gpol.GatePolicyError):
                _v(severity=sev, evidence="")


class PolicyResolutionTests(unittest.TestCase):
    """(gate, mode, lane) cap precedence + fail-closed resolution."""

    GATE = "geometry_feasibility"

    def setUp(self) -> None:
        self.policy = gpol.GatePolicy()
        self.policy.register(self.GATE, "FAIL")

    def test_fail_blocks_under_fail_default(self) -> None:
        self.assertEqual(self.policy.resolve(_v()), "block")

    def test_warn_advises(self) -> None:
        self.assertEqual(self.policy.resolve(_v(severity="WARN")), "advise")

    def test_skip_verdict_skips(self) -> None:
        v = _v(severity="SKIP", evidence="mezzanine proxy not rendered yet")
        self.assertEqual(self.policy.resolve(v), "skip")

    def test_unregistered_gate_raises_even_for_skip(self) -> None:
        v = _v(gate="unregistered_gate", severity="SKIP", evidence="why")
        with self.assertRaises(gpol.GatePolicyError):
            self.policy.resolve(v)

    def test_cap_demotes_fail_to_advise(self) -> None:
        self.policy.register("caption_band", "FAIL",
                             overrides={("short", None): "WARN"})
        v = _v(gate="caption_band", mode="short")
        self.assertEqual(self.policy.resolve(v), "advise")

    def test_cap_never_promotes_warn_to_block(self) -> None:
        self.policy.register("comp_size", "WARN")
        # Even though the declared severity is FAIL-capable, WARN stays advisory.
        self.assertEqual(self.policy.resolve(_v(gate="comp_size", severity="WARN")),
                         "advise")

    def test_policy_skip_cap_skips_a_fail(self) -> None:
        self.policy.register("shorts_only_gate", "FAIL",
                             overrides={("longform", None): "SKIP"})
        v = _v(gate="shorts_only_gate", mode="longform")
        self.assertEqual(self.policy.resolve(v), "skip")

    def test_precedence_exact_then_mode_then_lane_then_default(self) -> None:
        self.policy.register("layered", "FAIL", overrides={
            ("short", "graphics"): "SKIP",
            ("short", None): "WARN",
            (None, "graphics"): "FAIL",
        })
        eff = self.policy.effective_severity
        self.assertEqual(eff("layered", "short", "graphics"), "SKIP")
        self.assertEqual(eff("layered", "short", "captions"), "WARN")
        self.assertEqual(eff("layered", "longform", "graphics"), "FAIL")
        self.assertEqual(eff("layered", "longform", "captions"), "FAIL")

    def test_target_mode_used_when_verdict_mode_absent(self) -> None:
        self.policy.register("caption_band", "FAIL",
                             overrides={("short", None): "WARN"})
        v = _v(gate="caption_band", mode=None)
        self.assertEqual(self.policy.resolve(v, {"mode": "short"}), "advise")
        self.assertEqual(self.policy.resolve(v, {"mode": "longform"}), "block")

    def test_verdict_target_mode_disagreement_raises(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            self.policy.resolve(_v(mode="short"), {"mode": "longform"})

    def test_unknown_target_mode_raises(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            self.policy.resolve(_v(mode=None), {"mode": "vertical"})

    def test_identical_reregistration_is_idempotent(self) -> None:
        self.policy.register(self.GATE, "FAIL")  # double import must be safe
        self.assertEqual(self.policy.resolve(_v()), "block")

    def test_conflicting_reregistration_raises(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            self.policy.register(self.GATE, "WARN")

    def test_register_rejects_skip_default(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            self.policy.register("dark_gate", "SKIP")

    def test_register_rejects_bad_override_keys(self) -> None:
        cases = [
            {(None, None): "WARN"},          # the default's job
            {("short",): "WARN"},            # not a (mode, lane) pair
            {("vertical", None): "WARN"},    # unknown mode
            {(None, "music"): "WARN"},       # unknown lane
            {("short", None): "advise"},     # action, not a severity
        ]
        for overrides in cases:
            with self.assertRaises(gpol.GatePolicyError):
                self.policy.register("bad_gate", "FAIL", overrides=overrides)

    def test_module_level_registry_surface(self) -> None:
        gpol.register_gate("test_gate_policy_module_surface", "FAIL")
        gpol.register_gate("test_gate_policy_module_surface", "FAIL")  # idempotent
        action = gpol.resolve(_v(gate="test_gate_policy_module_surface"))
        self.assertEqual(action, "block")


class SeverityForTests(unittest.TestCase):
    """severity_for: WARN until calibrated, the declared default after."""

    def test_uncalibrated_demotes_to_warn(self) -> None:
        self.assertEqual(gpol.severity_for("lint", "FAIL", calibrated=False), "WARN")

    def test_calibrated_keeps_default(self) -> None:
        self.assertEqual(gpol.severity_for("lint", "FAIL", calibrated=True), "FAIL")

    def test_warn_default_stays_warn_both_ways(self) -> None:
        self.assertEqual(gpol.severity_for("lint", "WARN", calibrated=False), "WARN")
        self.assertEqual(gpol.severity_for("lint", "WARN", calibrated=True), "WARN")

    def test_skip_default_rejected(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            gpol.severity_for("lint", "SKIP", calibrated=True)

    def test_bad_gate_rejected(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            gpol.severity_for("", "FAIL", calibrated=True)


class GateJsonAdapterTests(unittest.TestCase):
    """to_gate_json: exact {ok, errors, warnings} contract, skips visible."""

    def setUp(self) -> None:
        self.policy = gpol.GatePolicy()
        self.policy.register("geometry_feasibility", "FAIL")
        self.policy.register("caption_band", "FAIL",
                             overrides={("short", None): "WARN"})

    def _assert_contract_shape(self, out: dict) -> None:
        """The exact checks planning-gates.ts parsePlanningGateVerdict runs."""
        self.assertIsInstance(out["ok"], bool)
        for key in ("errors", "warnings"):
            self.assertIsInstance(out[key], list)
            self.assertTrue(all(isinstance(m, str) for m in out[key]))
        # ok:false with empty errors is the degraded state the TS parser
        # patches over — the adapter must never produce it.
        if not out["ok"]:
            self.assertTrue(out["errors"])
        else:
            self.assertEqual(out["errors"], [])

    def test_fail_lands_in_errors_and_flips_ok(self) -> None:
        out = gpol.to_gate_json([_v()], policy=self.policy)
        self._assert_contract_shape(out)
        self.assertFalse(out["ok"])
        self.assertEqual(out["errors"],
                         ["geometry_feasibility: no legal region under punch 1.12"])
        self.assertEqual(out["warnings"], [])

    def test_warn_and_skip_land_in_warnings(self) -> None:
        verdicts = [
            _v(severity="WARN", evidence="clearance 12px under margin"),
            _v(severity="SKIP", evidence="no face samples in window"),
        ]
        out = gpol.to_gate_json(verdicts, policy=self.policy)
        self._assert_contract_shape(out)
        self.assertTrue(out["ok"])
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["warnings"], [
            "geometry_feasibility: clearance 12px under margin",
            "geometry_feasibility: SKIP — no face samples in window",
        ])

    def test_policy_demoted_fail_is_a_warning(self) -> None:
        v = _v(gate="caption_band", evidence="captions overlap chin band")
        out = gpol.to_gate_json([v], target={"mode": "short"}, policy=self.policy)
        self._assert_contract_shape(out)
        self.assertTrue(out["ok"])
        self.assertEqual(out["warnings"], ["caption_band: captions overlap chin band"])

    def test_policy_skip_cap_is_labeled_distinctly(self) -> None:
        self.policy.register("shorts_only", "FAIL",
                             overrides={("longform", None): "SKIP"})
        v = _v(gate="shorts_only", mode="longform", evidence="band conflict")
        out = gpol.to_gate_json([v], policy=self.policy)
        self.assertTrue(out["ok"])
        self.assertEqual(out["warnings"], ["shorts_only: SKIP (policy) — band conflict"])

    def test_empty_verdicts_pass_clean(self) -> None:
        out = gpol.to_gate_json([], policy=self.policy)
        self._assert_contract_shape(out)
        self.assertEqual(out, {"ok": True, "errors": [], "warnings": []})

    def test_mixed_verdicts_route_by_resolution(self) -> None:
        verdicts = [
            _v(evidence="hard conflict"),
            _v(gate="caption_band", mode="short", evidence="soft conflict"),
            _v(severity="SKIP", evidence="probe unavailable"),
        ]
        out = gpol.to_gate_json(verdicts, policy=self.policy)
        self._assert_contract_shape(out)
        self.assertFalse(out["ok"])
        self.assertEqual(out["errors"], ["geometry_feasibility: hard conflict"])
        self.assertEqual(len(out["warnings"]), 2)

    def test_output_is_json_serializable_and_stable(self) -> None:
        verdicts = [_v(), _v(severity="SKIP", evidence="probe unavailable")]
        out = gpol.to_gate_json(verdicts, policy=self.policy)
        self.assertEqual(json.loads(json.dumps(out)), out)

    def test_unregistered_gate_fails_loud_not_open(self) -> None:
        with self.assertRaises(gpol.GatePolicyError):
            gpol.to_gate_json([_v(gate="never_registered")], policy=self.policy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
