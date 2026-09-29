"""Adversarial tests for controller-owned catalog receipt issuance."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from _visual_plan_fixture import (
    candidate, catalog_records, clone, missing_catalog_record, opportunity,
    reseal_plan_receipts, visual_plan,
)
from planner.catalog_receipt_issuer import issue_catalog_receipts
from planner.catalog_receipt_issuer_cli import main as issuer_cli_main
from planner.catalog_receipt_pipeline import catalog_receipt_pipeline_sha256
from planner.visual_plan_contract import VisualPlanContractError, validate_visual_plan
from planner.visual_plan_fields import canonical_hash
from planner.visual_plan_receipts import authority_pin
from planner.visual_plan_cli import main as visual_plan_cli_main


def _base(route: str = "native") -> dict:
    return visual_plan(opportunity(
        "opp:one", 0, [candidate("candidate:one", "catalog", routeClass=route)]))


def _issue(plan: dict, root: str):
    return issue_catalog_receipts(plan, root)


def _manifest(result) -> tuple[Path, dict]:
    path = Path(result.authority["path"])
    return path, json.loads(path.read_text())


def _seal(path: Path, value: dict) -> dict:
    core = {key: item for key, item in value.items() if key != "digest"}
    value["digest"] = canonical_hash(core)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return authority_pin(str(path))


def _receipt_record(value: dict, kind: str = "source-inspection") -> dict:
    return next(row for row in value["records"] if row["kind"] == kind)


def _missing_dependency_candidate() -> dict:
    record = next(row for row in catalog_records()
                  if row["integration"]["status"] == "reference"
                  and row["resourceEvidence"].get(
                      "dependencySize", {}).get("missingReferences"))
    row = candidate("candidate:one", "catalog", routeClass="native")
    source, resource = record["source"], record["resourceEvidence"]
    row["source"] = {"recordId": record["id"], "path": source["path"],
                     "sha256": source["sha256"], "sourceSha256": source["sha256"]}
    row["catalogAdmission"] = {
        "catalogRecordSha256": canonical_hash(record), "executionStatus": "reference",
        "resourceClass": "dom-css" if resource.get("domCss") else "unknown",
        "runtimeQualificationRequired": True,
        "sourceInspectionEvidence": None}
    row["eligibility"] = "prerequisite"
    row["prerequisites"] = ["catalog-static-source-inspection-evidence"]
    return row


def _missing_source_candidate() -> dict:
    missing = missing_catalog_record()
    row = candidate("candidate:missing", "catalog", routeClass="native")
    source, resource = missing["source"], missing["resourceEvidence"]
    digest = source.get("sha256") or "0" * 64
    row["source"] = {"recordId": missing["id"], "path": source["path"],
                     "sha256": digest, "sourceSha256": digest}
    row["catalogAdmission"] = {
        "catalogRecordSha256": canonical_hash(missing),
        "executionStatus": "reference-missing-source",
        "resourceClass": "dom-css" if resource.get("domCss") else "unknown",
        "runtimeQualificationRequired": True,
        "sourceInspectionEvidence": None}
    row["eligibility"], row["prerequisites"] = "blocked", []
    row["exclusionReasons"] = ["catalog-source-unavailable"]
    return row


class CatalogReceiptIssuerTests(unittest.TestCase):
    """Only fixed successful controller executions may upgrade eligibility."""

    def test_success_admits_and_allocates_exact_native_catalog_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _issue(_base(), raw)
            row = result.plan["opportunities"][0]["candidates"][0]
            self.assertEqual((row["eligibility"], row["prerequisites"]),
                             ("eligible", []))
            self.assertIsNotNone(
                row["catalogAdmission"]["sourceInspectionEvidence"])
            self.assertTrue(
                row["catalogAdmission"]["runtimeQualificationRequired"])
            self.assertEqual(result.plan["allocation"]["route"], "native-short")

    def test_agent_cli_derives_pipeline_authority_and_emits_native_binding(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw, "pending.json")
            output = Path(raw, "receipted.json")
            source.write_text(json.dumps(_base()), encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                status = issuer_cli_main([str(source), str(output), raw])
            self.assertEqual(status, 0)
            issued = json.loads(stdout.getvalue())
            self.assertEqual(issued["pipelineAuthoritySha256"],
                             catalog_receipt_pipeline_sha256())
            self.assertEqual(validate_visual_plan(
                json.loads(output.read_text()), issued["authority"])["allocation"]["route"],
                "native-short")
            binding_out = StringIO()
            with redirect_stdout(binding_out), redirect_stderr(StringIO()):
                status = visual_plan_cli_main([
                    "binding", str(output), "--receipt-authority",
                    issued["authority"]["path"]])
            self.assertEqual(status, 0)
            binding = json.loads(binding_out.getvalue())
            self.assertEqual(binding["catalogReceiptAuthority"], issued["authority"])

    def test_author_rehashed_receipt_has_no_controller_authority(self) -> None:
        plan = _base("compatibility")
        reseal_plan_receipts(plan)
        with self.assertRaisesRegex(VisualPlanContractError, "out-of-band"):
            validate_visual_plan(plan)

    def test_extra_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _issue(_base(), raw)
            Path(result.directory, "author-extra.json").write_text("{}")
            with self.assertRaisesRegex(VisualPlanContractError, "extra or missing"):
                validate_visual_plan(result.plan, result.authority)

    def test_symlink_and_hardlink_are_rejected(self) -> None:
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                result = _issue(_base(), raw)
                _, value = _manifest(result)
                artifact = Path(_receipt_record(value)["artifact"]["path"])
                backup = Path(raw, f"{kind}-backup")
                shutil.copyfile(artifact, backup)
                if kind == "symlink":
                    artifact.unlink()
                    artifact.symlink_to(backup)
                else:
                    os.link(artifact, Path(raw, "outside-hardlink"))
                with self.assertRaisesRegex(VisualPlanContractError, "linked file"):
                    validate_visual_plan(result.plan, result.authority)

    def test_stale_nonce_is_rejected_even_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _issue(_base(), raw)
            path, value = _manifest(result)
            record = _receipt_record(value)
            receipt_path = Path(record["receipt"]["path"])
            receipt = json.loads(receipt_path.read_text())
            receipt["issuer"]["nonce"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
            digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            record["receipt"]["sha256"] = digest
            plan = clone(result.plan)
            plan["opportunities"][0]["candidates"][0]["catalogAdmission"][
                "sourceInspectionEvidence"] = copy.deepcopy(record["receipt"])
            pin = _seal(path, value)
            with self.assertRaisesRegex(VisualPlanContractError, "provenance"):
                validate_visual_plan(plan, pin)

    def test_wrong_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _issue(_base(), raw)
            _, value = _manifest(result)
            artifact = Path(_receipt_record(value)["artifact"]["path"])
            artifact.write_bytes(artifact.read_bytes() + b"tampered")
            with self.assertRaisesRegex(VisualPlanContractError, "artifact SHA-256"):
                validate_visual_plan(result.plan, result.authority)

    def test_wrong_tool_and_runtime_are_rejected_after_reseal(self) -> None:
        for field in ("runnerIdentity", "runtimeIdentity"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw:
                result = _issue(_base(), raw)
                path, value = _manifest(result)
                value[field]["sha256"] = "0" * 64
                header_keys = ("schemaVersion", "kind", "runId", "nonce",
                               "projectSha256", "catalogPinSha256",
                               "pipelineAuthoritySha256", "runnerIdentity", "runtimeIdentity")
                value["authorityId"] = canonical_hash(
                    {key: value[key] for key in header_keys})
                pin = _seal(path, value)
                with self.assertRaisesRegex(VisualPlanContractError, "tool or runtime"):
                    validate_visual_plan(result.plan, pin)

    def test_stale_pipeline_authority_is_rejected_after_reseal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _issue(_base(), raw)
            path, value = _manifest(result)
            value["pipelineAuthoritySha256"] = "0" * 64
            header_keys = ("schemaVersion", "kind", "runId", "nonce",
                           "projectSha256", "catalogPinSha256",
                           "pipelineAuthoritySha256", "runnerIdentity",
                           "runtimeIdentity")
            value["authorityId"] = canonical_hash(
                {key: value[key] for key in header_keys})
            pin = _seal(path, value)
            with self.assertRaisesRegex(VisualPlanContractError,
                                        "pipeline authority is stale"):
                validate_visual_plan(result.plan, pin)

    def test_unresolved_dependencies_remain_selectable_static_findings(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [_missing_dependency_candidate()]))
        with tempfile.TemporaryDirectory() as raw:
            result = _issue(plan, raw)
            row = result.plan["opportunities"][0]["candidates"][0]
            _, value = _manifest(result)
            artifact = Path(_receipt_record(value)["artifact"]["path"])
            inspection = json.loads(artifact.read_text())
            self.assertEqual((row["eligibility"], row["prerequisites"]),
                             ("eligible", []))
            self.assertTrue(inspection["missingReferences"])
            self.assertEqual(inspection["staticDependencyStatus"], "unresolved")
            self.assertEqual(inspection["approvalClaims"], {
                "runtime": False, "render": False, "quality": False})
            self.assertFalse(value["failures"])

    def test_missing_source_stays_blocked_without_inspection_receipt(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [_missing_source_candidate()]))
        with tempfile.TemporaryDirectory() as raw:
            result = _issue(plan, raw)
            row = result.plan["opportunities"][0]["candidates"][0]
            _, value = _manifest(result)
            self.assertEqual(row["eligibility"], "blocked")
            self.assertIn("catalog-source-unavailable", row["exclusionReasons"])
            self.assertFalse(value["records"])


if __name__ == "__main__":
    unittest.main()
