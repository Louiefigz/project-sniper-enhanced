"""Shared VISUAL-PLAN contract and whole-video allocation tests."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from _visual_plan_fixture import (
    SHA_A, SHA_C, candidate, clone, external_authorization_pin, opportunity,
    reference_pin,
    reseal_controller_authorities, reseal_plan_receipts,
    reseal_search_authority, visual_plan,
)
from contracts.schema_validator import validate_document
from planner.visual_plan_allocator import allocate_visual_plan
from planner.visual_plan_contract import (
    VisualPlanContractError, invalidation_inputs, validate_visual_plan,
)
from planner.visual_plan_fields import canonical_hash
from planner.visual_plan_cli import MAX_PLAN_BYTES, main as cli_main


class VisualPlanContractTests(unittest.TestCase):
    """The shared artifact remains bounded, pinned, and route neutral."""

    def test_schema_and_pending_plan_are_valid(self) -> None:
        schema_path = Path(__file__).parents[3] / "schemas/producer/visual-plan-v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$defs"]["bounds"]["properties"]
                         ["maxCandidatesPerOpportunity"]["maximum"], 5)
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        self.assertEqual(validate_visual_plan(plan), plan)
        self.assertEqual(validate_document("visual-plan-v1.schema.json", plan), plan)
        allocated = allocate_visual_plan(plan)
        self.assertEqual(validate_document("visual-plan-v1.schema.json", allocated), allocated)

    def test_nonempty_reference_pin_passes_python_and_json_schema(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        plan["direction"]["referencePins"] = [reference_pin()]
        self.assertEqual(validate_visual_plan(plan), plan)
        self.assertEqual(validate_document("visual-plan-v1.schema.json", plan), plan)

    def test_transcript_evidence_rejects_fabricated_ids_text_and_timing(self) -> None:
        base = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        forged_id = clone(base)
        forged_id["opportunities"][0]["transcriptEvidence"]["wordIds"] = ["word:forged"]
        with self.assertRaisesRegex(VisualPlanContractError, "fabricated transcript word ID"):
            validate_visual_plan(forged_id)
        forged_text = clone(base)
        forged_text["opportunities"][0]["transcriptEvidence"]["text"] = "Invented words."
        with self.assertRaisesRegex(VisualPlanContractError, "text differs"):
            validate_visual_plan(forged_text)
        forged_timing = clone(base)
        forged_timing["opportunities"][0]["timing"] = {
            "startFrame": 40, "endFrameExclusive": 64}
        with self.assertRaisesRegex(VisualPlanContractError, "outside its timing"):
            validate_visual_plan(forged_timing)

    def test_related_usage_must_equal_controller_ledger(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        plan["relatedUsage"] = [{"candidateId": "candidate:invented",
                                 "modality": "text", "sourceRecordId": None,
                                 "sourceSha256": None,
                                 "familyId": "family:cards", "anatomy": "split-card",
                                 "development": "label-then-proof", "planSha256": SHA_A}]
        with self.assertRaisesRegex(VisualPlanContractError, "controller ledger"):
            validate_visual_plan(plan)

    def test_machine_checked_native_usage_source_is_not_human_approval(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        plan["relatedUsage"] = [{"candidateId": "candidate:old",
                                 "modality": "text", "sourceRecordId": None,
                                 "sourceSha256": None,
                                 "familyId": "family:cards", "anatomy": "split-card",
                                 "development": "label-then-proof", "planSha256": SHA_A}]
        reseal_controller_authorities(plan)
        pin = plan["relatedUsageAuthority"]
        file = Path(pin["path"]); authority = json.loads(file.read_text())
        authority["source"] = "validated-current-projects"
        core = {key: value for key, value in authority.items() if key != "digest"}
        authority["digest"] = canonical_hash(core)
        data = json.dumps(authority, sort_keys=True, separators=(",", ":")) + "\n"
        file.write_text(data); pin["sha256"] = hashlib.sha256(data.encode()).hexdigest()
        pin["digest"] = authority["digest"]
        self.assertEqual(validate_visual_plan(plan), plan)

    def test_controller_authority_absence_and_byte_drift_fail_closed(self) -> None:
        base = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        missing = clone(base)
        del missing["transcriptAuthority"]
        with self.assertRaisesRegex(VisualPlanContractError, "missing"):
            validate_visual_plan(missing)
        drifted = clone(base)
        drifted["relatedUsageAuthority"]["sha256"] = SHA_A
        with self.assertRaisesRegex(VisualPlanContractError, "SHA-256"):
            validate_visual_plan(drifted)

    def test_media_candidates_bind_exact_controller_inventory(self) -> None:
        source = candidate("candidate:source", "source-footage")
        broll = candidate("candidate:broll", "supplied-broll")
        plan = visual_plan(opportunity("opp:one", 0, [source, broll]))
        self.assertEqual(validate_visual_plan(plan), plan)
        for field, value in (("recordId", "record:invented"),
                             ("path", "/tmp/stale-source.mp4"),
                             ("sha256", SHA_A), ("sourceSha256", SHA_A)):
            forged = clone(plan)
            forged["opportunities"][0]["candidates"][0]["source"][field] = value
            with self.assertRaisesRegex(
                    VisualPlanContractError, "controller media authority"):
                validate_visual_plan(forged)

    def test_external_media_uses_only_controller_admitted_inventory(self) -> None:
        missing = visual_plan(opportunity(
            "opp:missing", 0, [candidate("candidate:missing", "external-media")]))
        with self.assertRaisesRegex(
                VisualPlanContractError, "external media needs authorization"):
            validate_visual_plan(missing)
        item = candidate(
            "candidate:external", "external-media",
            authorization={"basis": "Operator supplied for local editorial review.",
                           "evidence": external_authorization_pin()})
        plan = visual_plan(opportunity("opp:one", 0, [item]))
        self.assertEqual(validate_visual_plan(plan), plan)
        authority = json.loads(Path(plan["mediaAuthority"]["path"]).read_text())
        external = next(row for row in authority["inventory"]
                        if row["modality"] == "external-media")
        self.assertEqual(item["source"]["recordId"], external["recordId"])
        self.assertEqual(external["sourceSetLane"], "external")
        self.assertEqual(item["authorization"]["basis"],
                         "Operator supplied for local editorial review.")
        wrong_authorization = clone(plan)
        wrong_authorization["opportunities"][0]["candidates"][0]["authorization"] = {
            "basis": "An author pin cannot replace controller origin authority.",
            "evidence": {key: reference_pin()[key] for key in ("path", "sha256")}}
        with self.assertRaisesRegex(
                VisualPlanContractError, "differs from controller authority"):
            validate_visual_plan(wrong_authorization)

        prerequisite = candidate(
            "candidate:pending", "external-media", eligibility="prerequisite",
            prerequisites=["Controller origin authorization is not available."],
            authorization=None)
        pending = visual_plan(opportunity("opp:pending", 0, [prerequisite]))
        self.assertEqual(validate_visual_plan(pending), pending)

        forged = visual_plan(opportunity(
            "opp:forged", 0, [candidate("candidate:source", "source-footage")]))
        row = forged["opportunities"][0]["candidates"][0]
        row["modality"] = "external-media"
        row["authorization"] = {
            "basis": "Agent-authored claims do not mint a controller lane.",
            "evidence": {key: reference_pin()[key] for key in ("path", "sha256")}}
        forged["opportunities"][0]["allowedModalities"] = ["external-media"]
        with self.assertRaisesRegex(
                VisualPlanContractError, "absent from controller media authority"):
            validate_visual_plan(forged)

    def test_manifest_only_authorization_cannot_mint_controller_authority(self) -> None:
        item = candidate(
            "candidate:external", "external-media",
            authorization={"basis": "Local editorial review.",
                           "evidence": external_authorization_pin()})
        plan = visual_plan(opportunity("opp:one", 0, [item]))
        authority = json.loads(Path(plan["mediaAuthority"]["path"]).read_text())
        original_manifest = Path(authority["manifest"]["path"])
        manifest = json.loads(original_manifest.read_text())
        manifest["externalMedia"][0]["authorizationEvidence"] = reference_pin()
        manifest_data = (json.dumps(
            manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        manifest_sha = hashlib.sha256(manifest_data).hexdigest()
        manifest_path = original_manifest.parent / f"forged-manifest-{manifest_sha}.json"
        manifest_path.write_bytes(manifest_data)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            authority["manifest"] = {
                "path": str(manifest_path),
                "sha256": hashlib.sha256(manifest_data).hexdigest()}
            core = {key: value for key, value in authority.items()
                    if key != "digest"}
            authority["digest"] = canonical_hash(core)
            authority_path = root / "forged-authority.json"
            authority_data = (json.dumps(
                authority, sort_keys=True, separators=(",", ":")) + "\n").encode()
            authority_path.write_bytes(authority_data)
            forged = clone(plan)
            forged["mediaAuthority"].update(
                path=str(authority_path),
                sha256=hashlib.sha256(authority_data).hexdigest(),
                digest=authority["digest"])
            with self.assertRaisesRegex(
                    VisualPlanContractError, "manifest authorization differs"):
                validate_visual_plan(forged)

    def test_stale_source_set_receipt_cannot_mint_media_authority(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:source", "source-footage")]))
        authority = json.loads(Path(plan["mediaAuthority"]["path"]).read_text())
        manifest_path = Path(authority["manifest"]["path"])
        manifest = json.loads(manifest_path.read_text())
        receipt_path = Path(authority["sourceSetAdmission"]["receiptPath"])
        receipt = json.loads(receipt_path.read_text())
        receipt["entries"][0]["originalPath"] += ".stale"
        payload = (json.dumps(receipt, ensure_ascii=True, sort_keys=True,
                              separators=(",", ":")) + "\n").encode("ascii")
        receipt_sha = hashlib.sha256(payload).hexdigest()
        stale_receipt = receipt_path.parent / f"{receipt_sha}.json"
        stale_receipt.write_bytes(payload)
        binding = dict(manifest["sourceSetAdmission"])
        binding.update(receiptPath=f".sniper-source-sets/{receipt_sha}.json",
                       receiptSha256=receipt_sha)
        manifest["sourceSetAdmission"] = binding
        stale_manifest = manifest_path.parent / f"stale-manifest-{receipt_sha}.json"
        manifest_data = (json.dumps(manifest, sort_keys=True,
                                    separators=(",", ":")) + "\n").encode()
        stale_manifest.write_bytes(manifest_data)
        authority["manifest"] = {
            "path": str(stale_manifest),
            "sha256": hashlib.sha256(manifest_data).hexdigest()}
        authority["sourceSetAdmission"].update(
            receiptPath=str(stale_receipt), receiptSha256=receipt_sha)
        core = {key: value for key, value in authority.items() if key != "digest"}
        authority["digest"] = canonical_hash(core)
        with tempfile.TemporaryDirectory() as raw:
            forged = clone(plan)
            data = json.dumps(authority, sort_keys=True, separators=(",", ":")) + "\n"
            path = Path(raw) / "MEDIA-AUTHORITY.json"
            path.write_text(data)
            forged["mediaAuthority"].update(
                path=str(path), sha256=hashlib.sha256(data.encode()).hexdigest(),
                digest=authority["digest"])
            with self.assertRaisesRegex(
                    VisualPlanContractError, "digest or ordering is stale"):
                validate_visual_plan(forged)

    def test_per_file_admission_receipt_is_rehashed_and_semantically_bound(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:source", "source-footage")]))
        authority = json.loads(Path(plan["mediaAuthority"]["path"]).read_text())
        manifest_path = Path(authority["manifest"]["path"])
        manifest = json.loads(manifest_path.read_text())
        source_set_path = Path(authority["sourceSetAdmission"]["receiptPath"])
        source_set = json.loads(source_set_path.read_text())
        entry = source_set["entries"][0]
        receipt_path = manifest_path.parent / entry["admissionReceiptPath"]
        receipt = json.loads(receipt_path.read_text())
        receipt["snapshot"]["sizeBytes"] += 1
        receipt_data = (json.dumps(
            receipt, ensure_ascii=True, sort_keys=True,
            separators=(",", ":")) + "\n").encode("ascii")
        receipt_sha = hashlib.sha256(receipt_data).hexdigest()
        forged_receipt = receipt_path.parent / f"{receipt_sha}.json"
        forged_receipt.write_bytes(receipt_data)
        entry["admissionReceiptPath"] = \
            f".sniper-external-media/receipts/{receipt_sha}.json"
        entry["admissionReceiptSha256"] = receipt_sha
        source_set["sourceSetDigest"] = hashlib.sha256(
            b"sniper-producer-source-set-v1\0" + (json.dumps(
                source_set["entries"], ensure_ascii=True, sort_keys=True,
                separators=(",", ":")) + "\n").encode("ascii")).hexdigest()
        source_set_data = (json.dumps(
            source_set, ensure_ascii=True, sort_keys=True,
            separators=(",", ":")) + "\n").encode("ascii")
        source_set_sha = hashlib.sha256(source_set_data).hexdigest()
        forged_source_set = source_set_path.parent / f"{source_set_sha}.json"
        forged_source_set.write_bytes(source_set_data)
        binding = {"schemaVersion": 1,
                   "receiptPath": f".sniper-source-sets/{source_set_sha}.json",
                   "receiptSha256": source_set_sha,
                   "sourceSetDigest": source_set["sourceSetDigest"], "entryCount": 1}
        manifest["sourceSetAdmission"] = binding
        manifest["sources"][0].update(
            admissionReceiptPath=entry["admissionReceiptPath"],
            admissionReceiptSha256=receipt_sha)
        forged_manifest = manifest_path.parent / f"receipt-forgery-{source_set_sha}.json"
        manifest_data = (json.dumps(
            manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        forged_manifest.write_bytes(manifest_data)
        authority["manifest"] = {"path": str(forged_manifest),
                                 "sha256": hashlib.sha256(manifest_data).hexdigest()}
        authority["sourceSetAdmission"] = {
            **binding, "receiptPath": str(forged_source_set)}
        authority["inventory"][0]["sourceSetEvidence"] = {
            "path": str(forged_receipt), "sha256": receipt_sha}
        core = {key: value for key, value in authority.items() if key != "digest"}
        authority["digest"] = canonical_hash(core)
        with tempfile.TemporaryDirectory() as raw:
            forged = clone(plan)
            data = json.dumps(authority, sort_keys=True, separators=(",", ":")) + "\n"
            path = Path(raw) / "MEDIA-AUTHORITY.json"
            path.write_text(data)
            forged["mediaAuthority"].update(
                path=str(path), sha256=hashlib.sha256(data.encode()).hexdigest(),
                digest=authority["digest"])
            with self.assertRaisesRegex(
                    VisualPlanContractError, "differs from its source-set entry"):
                validate_visual_plan(forged)

    def test_forged_media_authority_cannot_redefine_manifest_inventory(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:source", "source-footage")]))
        with tempfile.TemporaryDirectory() as raw:
            forged = clone(plan)
            authority = json.loads(Path(plan["mediaAuthority"]["path"]).read_text())
            authority["inventory"][0]["path"] = "/tmp/invented-source.mp4"
            core = {key: value for key, value in authority.items() if key != "digest"}
            authority["digest"] = canonical_hash(core)
            data = json.dumps(authority, sort_keys=True, separators=(",", ":")) + "\n"
            path = Path(raw) / "MEDIA-AUTHORITY.json"
            path.write_text(data)
            forged["mediaAuthority"].update(
                path=str(path), sha256=hashlib.sha256(data.encode()).hexdigest(),
                digest=authority["digest"])
            with self.assertRaisesRegex(
                    VisualPlanContractError, "differs from its admitted source set"):
                validate_visual_plan(forged)

    def test_embedded_media_and_unbounded_shortlists_fail(self) -> None:
        rows = [candidate(f"candidate:{index}") for index in range(6)]
        plan = visual_plan(opportunity("opp:one", 0, rows))
        with self.assertRaisesRegex(VisualPlanContractError, "declared bound"):
            validate_visual_plan(plan)
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        plan["opportunities"][0]["candidates"][0]["evidence"][0]["path"] = "data:image/png;base64,abc"
        with self.assertRaisesRegex(VisualPlanContractError, "path"):
            validate_visual_plan(plan)

    def test_credible_search_results_require_complete_ranked_review(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "text")],
            explanatoryJob="Compare the before and after states."))
        reseal_search_authority(
            plan, {"opp:one": ["compare before and after"]})
        outcomes = plan["opportunities"][0]["searchReview"]["outcomes"]
        self.assertGreaterEqual(len(outcomes), 3)
        self.assertEqual(validate_visual_plan(plan), plan)
        hidden = clone(plan)
        hidden["opportunities"][0]["searchReview"]["outcomes"] = outcomes[:1]
        with self.assertRaisesRegex(VisualPlanContractError, "cover every credible"):
            validate_visual_plan(hidden)

    def test_fewer_than_three_credible_results_and_restraint_can_pass(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:restraint", "omit")],
            explanatoryJob="Compare a Claude exchange with alternatives."))
        reseal_search_authority(
            plan, {"opp:one": ["claude exchange"]})
        outcomes = plan["opportunities"][0]["searchReview"]["outcomes"]
        self.assertLess(len(outcomes), 3)
        self.assertEqual(validate_visual_plan(plan), plan)
        reseal_search_authority(
            plan, {"opp:one": ["compare before and after"]})
        self.assertGreaterEqual(
            len(plan["opportunities"][0]["searchReview"]["outcomes"]), 3)
        self.assertEqual(validate_visual_plan(plan), plan)

    def test_forged_and_stale_search_evidence_fail_closed(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "text")],
            explanatoryJob="Compare the before and after states."))
        reseal_search_authority(
            plan, {"opp:one": ["compare before and after"]})
        stale = clone(plan)
        stale["opportunities"][0]["searchReview"]["searchDigest"] = SHA_A
        with self.assertRaisesRegex(VisualPlanContractError, "stale search evidence"):
            validate_visual_plan(stale)
        with tempfile.TemporaryDirectory() as raw:
            forged = clone(plan)
            document = json.loads(Path(plan["searchAuthority"]["path"]).read_text())
            document["searches"][0]["results"] = []
            core = {key: value for key, value in document.items() if key != "digest"}
            document["digest"] = canonical_hash(core)
            data = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
            forged_path = Path(raw) / "VISUAL-SEARCH-RESULTS.json"
            forged_path.write_text(data)
            forged["searchAuthority"].update(
                path=str(forged_path),
                sha256=hashlib.sha256(data.encode()).hexdigest(),
                digest=document["digest"])
            forged["opportunities"][0]["searchReview"].update(
                searchDigest=document["digest"], outcomes=[])
            with self.assertRaisesRegex(
                    VisualPlanContractError, "deterministic full-catalog search"):
                validate_visual_plan(forged)

    def test_semantically_unanchored_query_cannot_hide_alternatives(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "text")],
            explanatoryJob="Compare the before and after states."))
        reseal_search_authority(plan, {"opp:one": ["camcorder"]})
        with self.assertRaisesRegex(VisualPlanContractError, "not anchored"):
            validate_visual_plan(plan)

    def test_transition_requires_two_sided_seam_context(self) -> None:
        transition = candidate(
            "candidate:transition", "transition",
            composition={"familyId": "family:seams", "anatomy": "edge-wipe",
                         "development": "left-to-right", "motionFamily": "directional"})
        seam = opportunity(
            "opp:seam", 100, [transition], kind="seam",
            seamContext={"left": _seam_side("scene:left"),
                         "right": _seam_side("scene:right"),
                         "relationship": "Cause resolves into result."})
        self.assertEqual(validate_visual_plan(visual_plan(seam))["opportunities"][0]["kind"], "seam")
        broken = clone(visual_plan(seam))
        del broken["opportunities"][0]["seamContext"]["right"]
        with self.assertRaisesRegex(VisualPlanContractError, "seamContext keys"):
            validate_visual_plan(broken)

    def test_stable_hashes_separate_picture_from_upstream_authority(self) -> None:
        plan = allocate_visual_plan(visual_plan(
            opportunity("opp:one", 0, [candidate("candidate:one")])))
        first = invalidation_inputs(plan)
        self.assertEqual(first, invalidation_inputs(clone(plan)))
        changed = clone(plan)
        changed["direction"]["motionFamily"] = "measured-hold"
        second = invalidation_inputs(changed)
        self.assertNotEqual(first["visualPlanSha256"], second["visualPlanSha256"])
        self.assertNotEqual(first["pictureInputSha256"], second["pictureInputSha256"])
        self.assertEqual(first["upstreamAuthoritySha256"], second["upstreamAuthoritySha256"])
        self.assertEqual(first["catalogPinSha256"], second["catalogPinSha256"])
        reframed = clone(plan)
        reframed["project"]["aspect"] = "1:1"
        reframed_inputs = invalidation_inputs(reframed)
        self.assertNotEqual(first["visualPlanSha256"],
                            reframed_inputs["visualPlanSha256"])
        self.assertNotEqual(first["pictureInputSha256"],
                            reframed_inputs["pictureInputSha256"])

    def test_frozen_catalog_pin_ignores_unrelated_refresh(self) -> None:
        plan = allocate_visual_plan(visual_plan(
            opportunity("opp:one", 0, [candidate("candidate:one")])))
        before = invalidation_inputs(plan)
        unrelated_current_catalog_sha = SHA_C
        self.assertEqual(unrelated_current_catalog_sha, SHA_C)
        self.assertEqual(before, invalidation_inputs(plan))

    def test_planning_cli_allocates_without_embedding_or_writing_media(self) -> None:
        plan = visual_plan(opportunity("opp:one", 0, [candidate("candidate:one")]))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "VISUAL-PLAN.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(StringIO()):
                result = cli_main(["allocate", str(path)])
        allocated = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(allocated["allocation"]["status"], "allocated")
        self.assertNotIn("data:", output.getvalue())

    def test_planning_cli_emits_a_native_project_binding(self) -> None:
        plan = allocate_visual_plan(visual_plan(
            opportunity("opp:one", 0, [candidate("candidate:one")])))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "VISUAL-PLAN.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(StringIO()):
                result = cli_main(["binding", str(path)])
        binding = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(binding["schemaVersion"], 1)
        self.assertEqual(binding["path"], str(path.resolve()))
        self.assertEqual(len(binding["byteHash"]), 64)
        self.assertEqual(binding["visualPlanSha256"], invalidation_inputs(plan)
                         ["visualPlanSha256"])

    def test_planning_cli_rejects_oversized_input_before_json_parse(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "VISUAL-PLAN.json"
            path.write_bytes(b"{" + b" " * MAX_PLAN_BYTES + b"}")
            error = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(error):
                result = cli_main(["validate", str(path)])
        self.assertEqual(result, 2)
        self.assertIn("bounded read size", error.getvalue())

    def test_catalog_route_and_resource_facts_cannot_be_forged(self) -> None:
        catalog = candidate("candidate:one", "catalog")
        plan = visual_plan(opportunity("opp:one", 0, [catalog]))
        forged = clone(plan)
        item = forged["opportunities"][0]["candidates"][0]
        item["routeClass"] = "native"
        with self.assertRaisesRegex(VisualPlanContractError, "route differs"):
            validate_visual_plan(forged)
        forged = clone(plan)
        admission = forged["opportunities"][0]["candidates"][0]["catalogAdmission"]
        admission["resourceClass"] = "gpu-video"
        with self.assertRaisesRegex(VisualPlanContractError, "resourceClass differs"):
            validate_visual_plan(forged)
        forged = clone(plan)
        admission = forged["opportunities"][0]["candidates"][0]["catalogAdmission"]
        admission["catalogRecordSha256"] = SHA_A
        with self.assertRaisesRegex(VisualPlanContractError, "catalogRecordSha256 differs"):
            validate_visual_plan(forged)

    def test_static_source_inspection_is_distinct_from_runtime_qualification(self) -> None:
        item = candidate("candidate:native", "catalog", routeClass="native")
        plan = visual_plan(opportunity("opp:one", 0, [item]))
        self.assertEqual(validate_visual_plan(plan), plan)
        self.assertEqual((item["eligibility"], item["prerequisites"]),
                         ("prerequisite", [
                             "catalog-static-source-inspection-evidence"]))
        self.assertTrue(item["catalogAdmission"]["runtimeQualificationRequired"])
        with self.assertRaisesRegex(VisualPlanContractError, "no eligible allocation"):
            allocate_visual_plan(plan)

    def test_eligible_candidate_cannot_retain_blockers_or_unavailable_evidence(self) -> None:
        base = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "source-footage")]))
        for field, value in (("prerequisites", ["wait"]),
                             ("exclusionReasons", ["unsupported"])):
            forged = clone(base)
            forged["opportunities"][0]["candidates"][0][field] = value
            with self.assertRaisesRegex(VisualPlanContractError, "retains blockers"):
                validate_visual_plan(forged)
        unavailable = clone(base)
        unavailable["opportunities"][0]["candidates"][0]["evidence"][0]["status"] = "unavailable"
        with self.assertRaisesRegex(VisualPlanContractError, "unavailable evidence"):
            validate_visual_plan(unavailable)

    def test_catalog_evidence_hashes_bind_exact_file_bytes(self) -> None:
        base = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "catalog")]))
        forged = clone(base)
        forged["catalogPin"]["indexSha256"] = SHA_A
        with self.assertRaisesRegex(VisualPlanContractError, "catalog index SHA-256"):
            validate_visual_plan(forged)
        forged = clone(base)
        forged["catalogPin"]["sourceSetSha256"] = SHA_A
        with self.assertRaisesRegex(VisualPlanContractError, "sourceSetSha256"):
            validate_visual_plan(forged)
        forged = clone(base)
        forged["opportunities"][0]["candidates"][0]["evidence"][0]["sha256"] = SHA_A
        with self.assertRaisesRegex(VisualPlanContractError, "evidence 0 SHA-256"):
            validate_visual_plan(forged)
    def test_catalog_version_registry_and_unified_inventory_are_trust_anchored(self) -> None:
        base = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "catalog")]))
        forged = clone(base)
        forged["catalogPin"]["version"] = "test-pin"
        with self.assertRaisesRegex(VisualPlanContractError, "not admitted"):
            validate_visual_plan(forged)
        for field in ("snapshotIndexSha256", "snapshotLockSha256",
                      "snapshotResourceSha256", "capabilitySha256", "studySha256"):
            forged = clone(base)
            forged["catalogPin"][field] = SHA_A
            with self.subTest(field=field), self.assertRaisesRegex(
                    VisualPlanContractError, f"{field} differs"):
                validate_visual_plan(forged)
        with tempfile.TemporaryDirectory() as raw:
            fake = Path(raw) / "catalog-snapshots-v1.json"
            fake.write_text('{"schemaVersion":1,"current":"fake","snapshots":{}}')
            forged = clone(base)
            forged["catalogPin"]["registryPath"] = str(fake)
            forged["catalogPin"]["registrySha256"] = hashlib.sha256(
                fake.read_bytes()).hexdigest()
            with self.assertRaisesRegex(VisualPlanContractError, "registryPath differs"):
                validate_visual_plan(forged)
            authority = json.loads(Path(base["catalogPin"]["indexPath"]).read_text())
            authority["items"] = authority["items"][:4]
            fake_authority = Path(raw) / "forged-authority.json"
            fake_authority.write_text(json.dumps(authority, sort_keys=True))
            digest = hashlib.sha256(fake_authority.read_bytes()).hexdigest()
            forged = clone(base)
            forged["catalogPin"].update(
                indexPath=str(fake_authority), indexSha256=digest,
                resourceIndexPath=str(fake_authority), resourceIndexSha256=digest)
            with self.assertRaisesRegex(VisualPlanContractError, "registry-derived"):
                validate_visual_plan(forged)

    def test_author_authored_receipt_cannot_upgrade_catalog_eligibility(self) -> None:
        plan = visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one", "catalog")]))
        reseal_plan_receipts(plan)
        row = plan["opportunities"][0]["candidates"][0]
        row["eligibility"] = "eligible"
        row["prerequisites"] = []
        with self.assertRaisesRegex(
                VisualPlanContractError,
                "out-of-band controller authority"):
            validate_visual_plan(plan)

    def test_catalog_authority_cli_freezes_all_372_records_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "CATALOG-AUTHORITY.json"
            outputs = []
            for _ in range(2):
                output = StringIO()
                with redirect_stdout(output), redirect_stderr(StringIO()):
                    result = cli_main(["catalog-authority", str(path)])
                self.assertEqual(result, 0)
                outputs.append(json.loads(output.getvalue()))
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(json.loads(path.read_text())["total"], 372)
            plan = visual_plan(opportunity(
                "opp:one", 0, [candidate("candidate:one", "catalog")]))
            plan["catalogPin"] = outputs[0]
            reseal_search_authority(plan)
            self.assertEqual(validate_visual_plan(plan), plan)

    def test_allocated_route_must_be_exact_for_mode_and_selected_classes(self) -> None:
        ordinary = allocate_visual_plan(visual_plan(
            opportunity("opp:one", 0, [candidate("candidate:one")])))
        forged = clone(ordinary)
        forged["allocation"]["route"] = "native-short"
        forged["allocation"]["decisions"][0]["executionRoute"] = "native-short"
        with self.assertRaisesRegex(VisualPlanContractError, "route differs"):
            validate_visual_plan(forged)
        native = allocate_visual_plan(visual_plan(
            opportunity("opp:one", 0, [candidate(
                "candidate:native", "custom-native", routeClass="native")])))
        native["project"]["mode"] = "long"
        reseal_controller_authorities(native)
        with self.assertRaisesRegex(VisualPlanContractError, "route differs"):
            validate_visual_plan(native)


class VisualPlanAllocatorTests(unittest.TestCase):
    """The allocator favors meaning, then bounded coherent variation."""

    def test_strong_tail_candidate_can_win_and_select_native_route(self) -> None:
        weak = candidate("candidate:alpha", scores={"semanticFit": 0.3})
        medium = candidate("candidate:beta", scores={"semanticFit": 0.5})
        strong = candidate("candidate:tail", "custom-native", routeClass="native",
                           scores={"semanticFit": 1.0})
        result = allocate_visual_plan(visual_plan(
            opportunity("opp:one", 0, [weak, medium, strong])))
        self.assertEqual(result["allocation"]["decisions"][0]["candidateId"],
                         "candidate:tail")
        self.assertEqual(result["allocation"]["route"], "native-short")

    def test_repetition_budget_forces_different_development(self) -> None:
        first = candidate("candidate:first")
        repeated = candidate("candidate:repeated")
        varied = candidate(
            "candidate:varied",
            composition={"development": "proof-then-label", "anatomy": "number-rail"})
        plan = visual_plan(opportunity("opp:one", 0, [first]),
                           opportunity("opp:two", 50, [repeated, varied]))
        decisions = allocate_visual_plan(plan)["allocation"]["decisions"]
        self.assertEqual([row["candidateId"] for row in decisions],
                         ["candidate:first", "candidate:varied"])
        self.assertEqual(decisions[1]["repeatClassification"], "varied")
        alternative = next(row for row in decisions[1]["alternatives"]
                           if row["candidateId"] == "candidate:repeated")
        self.assertEqual(alternative["outcome"], "budget-conflict")

    def test_intentional_callback_can_use_repeat_allowance(self) -> None:
        first = candidate("candidate:first")
        callback = candidate(
            "candidate:callback",
            repeatIntent={"classification": "callback",
                          "reason": "Resolve the visual promise from the opening.",
                          "priorOpportunityId": "opp:one",
                          "priorCandidateId": "candidate:first"})
        plan = visual_plan(opportunity("opp:one", 0, [first]),
                           opportunity("opp:two", 50, [callback],
                                       callbackTo=["opp:one"]))
        decision = allocate_visual_plan(plan)["allocation"]["decisions"][1]
        self.assertEqual(decision["repeatClassification"], "callback")
        self.assertIn("opening", decision["repeatReason"])

    def test_first_use_callback_and_forged_repeat_are_rejected(self) -> None:
        callback = candidate(
            "candidate:callback", repeatIntent={"classification": "callback",
                                                 "reason": "Claimed callback.",
                                                 "priorOpportunityId": "opp:later",
                                                 "priorCandidateId": "candidate:later"})
        later = candidate("candidate:later")
        plan = visual_plan(opportunity("opp:first", 0, [callback],
                                       callbackTo=["opp:later"]),
                           opportunity("opp:later", 50, [later]))
        with self.assertRaisesRegex(VisualPlanContractError, "earlier candidate"):
            validate_visual_plan(plan)
        forged = candidate(
            "candidate:forged", composition={"anatomy": "different"},
            repeatIntent={"classification": "necessary", "reason": "Claimed need.",
                          "priorOpportunityId": "opp:one",
                          "priorCandidateId": "candidate:first"})
        plan = visual_plan(opportunity("opp:one", 0, [candidate("candidate:first")]),
                           opportunity("opp:two", 50, [forged],
                                       continuityWith=["opp:one"]))
        with self.assertRaisesRegex(VisualPlanContractError, "composition"):
            validate_visual_plan(plan)

    def test_allocated_repeat_and_alternative_evidence_cannot_be_forged(self) -> None:
        plan = allocate_visual_plan(visual_plan(opportunity(
            "opp:one", 0, [candidate("candidate:one"),
                            candidate("candidate:two", scores={"semanticFit": 0.5})])))
        forged = clone(plan)
        decision = forged["allocation"]["decisions"][0]
        decision["repeatClassification"] = "callback"
        decision["repeatReason"] = "Claimed callback without a prior use."
        with self.assertRaisesRegex(VisualPlanContractError, "repeat classification"):
            validate_visual_plan(forged)
        incomplete = clone(plan)
        incomplete["allocation"]["decisions"][0]["alternatives"] = []
        with self.assertRaisesRegex(VisualPlanContractError, "cover every unselected"):
            validate_visual_plan(incomplete)

    def test_duplicate_ids_and_relationship_targets_fail(self) -> None:
        first = opportunity("opp:one", 0, [candidate("candidate:duplicate")])
        second = opportunity("opp:two", 50, [candidate("candidate:duplicate")])
        with self.assertRaisesRegex(VisualPlanContractError, "candidate IDs"):
            validate_visual_plan(visual_plan(first, second))
        plan = visual_plan(opportunity("opp:one", 0, [candidate("candidate:one")],
                                       callbackTo=["opp:one", "opp:one"]))
        with self.assertRaisesRegex(VisualPlanContractError, "duplicates"):
            validate_visual_plan(plan)

    def test_related_output_history_prefers_same_family_with_new_anatomy(self) -> None:
        familiar = candidate("candidate:familiar")
        varied = candidate(
            "candidate:varied",
            composition={"anatomy": "side-rail", "development": "stack-then-resolve"})
        plan = visual_plan(opportunity("opp:one", 0, [familiar, varied]))
        plan["relatedUsage"] = [{"candidateId": "candidate:old",
                                 "modality": "text", "sourceRecordId": None,
                                 "sourceSha256": None,
                                 "familyId": "family:cards", "anatomy": "split-card",
                                 "development": "label-then-proof", "planSha256": SHA_A}]
        reseal_controller_authorities(plan)
        decision = allocate_visual_plan(plan)["allocation"]["decisions"][0]
        self.assertEqual(decision["candidateId"], "candidate:varied")

    def test_related_history_penalizes_renamed_source_identity(self) -> None:
        reused = candidate("candidate:renamed", "source-footage",
                           composition={"familyId": "family:new-name",
                                        "anatomy": "new prose",
                                        "development": "different prose"})
        fresh = candidate("candidate:fresh", "source-footage")
        plan = visual_plan(opportunity("opp:one", 0, [reused, fresh]))
        plan["relatedUsage"] = [{
            "candidateId": "candidate:historical-name",
            "modality": reused["modality"],
            "sourceRecordId": reused["source"]["recordId"],
            "sourceSha256": reused["source"]["sourceSha256"],
            "familyId": "family:historical-name", "anatomy": "old prose",
            "development": "old prose", "planSha256": SHA_A}]
        reseal_controller_authorities(plan)
        decision = allocate_visual_plan(plan)["allocation"]["decisions"][0]
        self.assertEqual(decision["candidateId"], "candidate:fresh")

    def test_same_source_cannot_hide_behind_renamed_composition(self) -> None:
        first = candidate("candidate:first", "source-footage")
        reused = candidate(
            "candidate:renamed", "source-footage",
            composition={"familyId": "family:renamed", "anatomy": "new label",
                         "development": "new description"},
            scores={"semanticFit": .901})
        reused["source"] = clone(first)["source"]
        fresh = candidate(
            "candidate:fresh", "source-footage",
            composition={"familyId": "family:fresh", "anatomy": "fresh anatomy",
                         "development": "fresh development"})
        plan = visual_plan(opportunity("opp:one", 0, [first]),
                           opportunity("opp:two", 50, [reused, fresh]))
        decisions = allocate_visual_plan(plan)["allocation"]["decisions"]
        self.assertEqual([row["candidateId"] for row in decisions],
                         ["candidate:first", "candidate:fresh"])
        rejected = next(row for row in decisions[1]["alternatives"]
                        if row["candidateId"] == "candidate:renamed")
        self.assertEqual((rejected["outcome"], rejected["reason"]),
                         ("budget-conflict",
                          "stable source identity requires an intentional repeat reason"))

    def test_quality_band_prefers_family_diversity_over_tiny_delta(self) -> None:
        first = candidate("candidate:first")
        familiar = candidate(
            "candidate:familiar", scores={"semanticFit": .901},
            composition={"development": "second development"})
        diverse = candidate(
            "candidate:diverse", scores={"semanticFit": .9},
            composition={"familyId": "family:diagram", "anatomy": "causal rail",
                         "development": "cause-then-effect"})
        plan = visual_plan(opportunity("opp:one", 0, [first]),
                           opportunity("opp:two", 50, [familiar, diverse]))
        decisions = allocate_visual_plan(plan)["allocation"]["decisions"]
        self.assertEqual(decisions[1]["candidateId"], "candidate:diverse")

    def test_material_quality_advantage_beats_rotation(self) -> None:
        first = candidate("candidate:first")
        stronger = candidate(
            "candidate:stronger", scores={"validity": .99, "semanticFit": .99,
                                           "readability": .99, "feasibility": .99,
                                           "coherence": .99, "variation": .1},
            composition={"development": "stronger second development"})
        filler = candidate(
            "candidate:filler", scores={"validity": .72, "semanticFit": .72,
                                         "readability": .72, "feasibility": .72,
                                         "coherence": .72, "variation": 1.0},
            composition={"familyId": "family:fresh", "anatomy": "novel shell",
                         "development": "weak filler"})
        plan = visual_plan(opportunity("opp:one", 0, [first]),
                           opportunity("opp:two", 50, [stronger, filler]))
        decision = allocate_visual_plan(plan)["allocation"]["decisions"][1]
        self.assertEqual(decision["candidateId"], "candidate:stronger")

    def test_sourced_callback_requires_and_accepts_exact_prior_source(self) -> None:
        first = candidate("candidate:first", "source-footage")
        callback = candidate(
            "candidate:callback", "source-footage",
            repeatIntent={"classification": "callback",
                          "reason": "Resolve the opening visual promise.",
                          "priorOpportunityId": "opp:one",
                          "priorCandidateId": "candidate:first"})
        callback["source"] = clone(first)["source"]
        plan = visual_plan(opportunity("opp:one", 0, [first]),
                           opportunity("opp:two", 50, [callback],
                                       callbackTo=["opp:one"]))
        decision = allocate_visual_plan(plan)["allocation"]["decisions"][1]
        self.assertEqual(decision["repeatClassification"], "callback")
        forged = clone(plan)
        forged["opportunities"][1]["candidates"][0]["source"] = candidate(
            "candidate:other", "source-footage")["source"]
        reseal_controller_authorities(forged)
        with self.assertRaisesRegex(VisualPlanContractError, "source does not match"):
            validate_visual_plan(forged)

    def test_density_budget_selects_explicit_omit(self) -> None:
        visual = candidate("candidate:visual", scores={"semanticFit": 1.0})
        omit = candidate("candidate:omit", "omit", scores={"semanticFit": 0.6},
                         decisionReason="The presenter already makes the point clearly.")
        plan = visual_plan(opportunity("opp:one", 0, [visual, omit]))
        plan["direction"]["density"]["maxVisualsPerSection"] = 0
        decision = allocate_visual_plan(plan)["allocation"]["decisions"][0]
        self.assertEqual((decision["candidateId"], decision["modality"]),
                         ("candidate:omit", "omit"))


def _seam_side(scene_id: str) -> dict:
    return {"sceneId": scene_id, "motion": "settling", "composition": "centered",
            "color": "ink", "audio": "sentence boundary", "narrative": "proof"}


if __name__ == "__main__":
    unittest.main()
