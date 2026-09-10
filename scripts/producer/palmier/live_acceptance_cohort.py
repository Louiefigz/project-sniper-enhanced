"""Build, prove, review, and repair one isolated Palmier acceptance cohort."""
from __future__ import annotations

from typing import Any

from palmier.desktop_audio_authority import require_audio_authority
from palmier.desktop_authority import advance, approve, begin, run_qc
from palmier.desktop_caption_pages import require_caption_pages_ready
from palmier.desktop_caption_shards import (
    require_broll_layers_ready, require_graphics_shards_ready,
    require_title_shards_ready,
)
from palmier.desktop_exact_master_contract import require_exact_master_ready
from palmier.desktop_motion import require_motion_ready
from palmier.desktop_state import (
    DesktopStageInput, load_state, save_state)
from palmier.desktop_visual_stack import require_visual_stack
from palmier.live_acceptance_media import revalidate_bootstrap
from palmier.live_acceptance_project_safety import (
    record_protected_checkpoint, require_active_project,
)
from palmier.live_acceptance_proofs import (
    ManualProofInput, RepairProofInput, final_mtimes,
    prove_manual_preservation, repair_delta, repair_scope,
)
from palmier.live_acceptance_session import (
    Evidence, LiveAcceptanceConfig, capture_prior, created_project,
    disposable_name,
)
from palmier.live_acceptance_worklist import GovernedWorklist
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import read_active


def _create_project(
        client: Any, config: LiveAcceptanceConfig,
        evidence: Evidence, prior_paths: set[str]) -> dict:
    name = disposable_name(config, evidence.value["runId"])
    evidence.phase("projectIntent", {"name": name})
    client.call_json("new_project", {
        "name": name, "fps": config.fps, "aspectRatio": config.aspect,
        "quality": config.quality})
    project = created_project(client, name, prior_paths)
    evidence.phase("project", {
        "name": name, "id": project.get("id"), "path": project.get("path")})
    return project


def _bootstrap(
        client: Any, config: LiveAcceptanceConfig,
        evidence: Evidence, project: dict) -> dict:
    before = revalidate_bootstrap(config, evidence.value["preflight"])
    require_active_project(client, project["id"])
    imported = client.call_json("import_media", {
        "source": {"path": config.bootstrap_path},
        "name": f"Sniper {config.format} editable base"})
    ref = imported.get("mediaRef")
    if not isinstance(ref, str):
        raise PalmierError("bootstrap import returned no mediaRef")
    after = revalidate_bootstrap(config, evidence.value["preflight"])
    client.wait_media(ref)
    target = evidence.value["preflight"]["targetFrames"]
    require_active_project(client, project["id"])
    client.call_json("add_clips", {"entries": [{
        "mediaRef": ref, "startFrame": 0, "endFrame": target}]})
    found = read_active(client, project["id"])
    expected = (config.fps, *evidence.value["preflight"]["canvas"], target)
    actual = (found.timeline.get("fps"), found.timeline.get("width"),
              found.timeline.get("height"), found.timeline.get("totalFrames"))
    if actual != expected or found.coverage.get("complete") is not True:
        raise PalmierError(f"bootstrap Palmier facts {actual} != {expected}")
    return {
        "mediaRef": ref, "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint, "facts": list(actual),
        "authorityBeforeImport": before, "authorityAfterImport": after,
    }


def _inputs(
        config: LiveAcceptanceConfig, plan: str,
        stage: str) -> DesktopStageInput:
    return DesktopStageInput(
        config.repo, config.out_dir, plan, config.manifest_path, stage,
        config.transcripts_dir)


def _visual(client: Any, config: LiveAcceptanceConfig,
            project: dict) -> dict:
    require_active_project(client, project["id"])
    with client.phase("candidate-fork"):
        authority = begin(
            client, _inputs(config, config.plan_path, "visual"))
    if authority.get("projectId") != project["id"]:
        raise PalmierError("Desktop candidate fork targeted another project")
    candidate = read_active(client, authority["projectId"])
    driver = GovernedWorklist(
        client, config.repo, candidate.timeline, fault_every_mutation=True)
    with client.phase("desktop-journal"):
        execution = driver.execute(authority["operations"]["path"])
    state = load_state(config.out_dir)
    found = read_active(client, state["projectId"])
    require_exact_master_ready(state, found.timeline, found.coverage)
    results = {
        "audioAuthority": require_audio_authority(state, found),
        "captionAuthority": require_caption_pages_ready(state, found.timeline),
        "titleCardAuthority": require_title_shards_ready(state, found.timeline),
        "graphicsAuthority": require_graphics_shards_ready(
            state, found.timeline),
        "brollAuthority": require_broll_layers_ready(state, found.timeline),
        "visualStackAuthority": require_visual_stack(state, found.timeline),
        "motionAuthority": require_motion_ready(state),
    }
    if state["operationCount"] != len(driver.calls):
        raise PalmierError("visual operation ledger count differs from live calls")
    result = {
        "candidateTimelineId": found.timeline_id,
        "candidateFingerprint": found.fingerprint,
        "readbackCoverage": found.coverage, "execution": execution,
        "exactMasterReference": state.get("exactMasterReference"), **results,
    }
    proof = {
        "kind": "candidate-visual-readback",
        "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint,
        "coverageComplete": found.coverage.get("complete"),
    }
    client.bind_proof("candidate-fork", proof)
    client.bind_proof("desktop-journal", proof)
    return result


def _repair(
        client: Any, config: LiveAcceptanceConfig,
        expected_element_id: str
) -> dict:
    before_state = load_state(config.out_dir)
    before = read_active(client, before_state["projectId"]).timeline
    files_before = final_mtimes(config.out_dir)
    authority = advance(
        client, _inputs(config, config.repair_plan_path, "repair"))
    _manifest, ident = repair_scope(
        authority["operations"]["path"], expected_element_id)
    prior = ((before_state.get("elementLedger") or {}).get(
        "elements") or {}).get(ident)
    if not isinstance(prior, dict):
        raise PalmierError("repair target has no prior element authority")
    driver = GovernedWorklist(
        client, config.repo, before, fault_every_mutation=True)
    with client.phase("desktop-journal"):
        execution = driver.execute(authority["operations"]["path"])
    state = load_state(config.out_dir)
    found = read_active(client, state["projectId"])
    require_exact_master_ready(state, found.timeline, found.coverage)
    require_audio_authority(state, found)
    delta = repair_delta(RepairProofInput(
        before, found.timeline, state, ident, files_before, prior))
    result = {
        **delta, "execution": execution,
        "candidateFingerprint": found.fingerprint,
    }
    client.bind_proof("desktop-journal", {
        "kind": "scoped-repair-readback",
        "fingerprint": found.fingerprint,
        "elementId": ident, "deltaChecks": delta["checks"],
    })
    return result


def _qc(client: Any, config: LiveAcceptanceConfig) -> dict:
    with client.phase("qc-export"):
        state = run_qc(client, config.repo)
    qc = state.get("qc") or {}
    export, audit = qc.get("export") or {}, qc.get("audit") or {}
    if state.get("status") != "review-required" or audit.get("status") != "pass":
        raise PalmierError("connected candidate did not reach passed Audit B")
    result = {
        "status": state["status"], "export": export,
        "audit": {key: audit.get(key) for key in (
            "status", "digest", "auditPath", "auditHash")},
        "candidateFingerprint": state["expectedFingerprint"],
    }
    client.bind_proof("qc-export", {
        "kind": "candidate-export-audit",
        "fingerprint": state["expectedFingerprint"],
        "exportHash": export.get("hash"), "auditDigest": audit.get("digest"),
    })
    return result


def _approve(
        client: Any, config: LiveAcceptanceConfig,
        evidence: Evidence) -> dict:
    path = config.reviews_path
    if not isinstance(path, str):
        raise PalmierError("resume requires real rendered reviews")
    state = approve(client, config.repo, path)
    expected = ((evidence.value["phases"].get("qc") or {})
                .get("candidateFingerprint"))
    if state.get("status") != "complete" \
            or state.get("expectedFingerprint") != expected:
        raise PalmierError("rendered review approved another candidate")
    return {
        "status": "complete", "candidateFingerprint": expected,
        "reviews": state.get("reviews"),
    }


def build_cohort(
        client: Any, config: LiveAcceptanceConfig,
        evidence: Evidence) -> tuple[dict, dict]:
    """Create, build, and retain one deterministic-QC candidate for review."""
    prior = capture_prior(client)
    evidence.phase("prior", prior)
    record_protected_checkpoint(
        client, evidence, "protectedBefore", prior["surface"])
    prior_paths = set(prior["knownProjectPaths"])
    with client.phase("project-lifecycle"):
        project = _create_project(
            client, config, evidence, prior_paths)
    client.bind_proof("project-lifecycle", {
        "kind": "created-project-readback", "projectId": project.get("id"),
        "path": project.get("path"), "name": project.get("name"),
    })
    with client.phase("bootstrap-authority"):
        bootstrap = _bootstrap(client, config, evidence, project)
    client.bind_proof("bootstrap-authority", {
        "kind": "bootstrap-timeline-readback",
        "timelineId": bootstrap["timelineId"],
        "fingerprint": bootstrap["fingerprint"],
        "facts": bootstrap["facts"],
    })
    evidence.phase("bootstrap", bootstrap)
    evidence.phase("visual", _visual(client, config, project))
    evidence.phase("qc", _qc(client, config))
    return prior, project


def _retained(
        client: Any, config: LiveAcceptanceConfig,
        evidence: Evidence) -> dict:
    project = evidence.value["phases"].get("project")
    if not isinstance(project, dict) or not isinstance(
            project.get("path"), str):
        raise PalmierError("resume evidence has no retained project")
    state = load_state(config.out_dir)
    with client.phase("project-lifecycle"):
        client.call_json("open_project", {"path": project["path"]})
        client.call_json("set_active_timeline", {
            "timelineId": state["candidate"]["timelineId"]})
    save_state(config.repo, state)
    found = read_active(client, state["projectId"])
    expected = ((evidence.value["phases"].get("qc") or {})
                .get("candidateFingerprint"))
    valid = (
        project.get("id") == state.get("projectId")
        and found.timeline_id == state["candidate"]["timelineId"]
        and found.fingerprint == expected)
    if not valid:
        raise PalmierError("retained review candidate changed before resume")
    return project


def resume_cohort(
        client: Any, config: LiveAcceptanceConfig,
        evidence: Evidence) -> tuple[dict, dict]:
    """Approve real reviews, prove scoped repair/manual safety, then finish."""
    prior = capture_prior(client)
    evidence.phase("resumePrior", prior)
    record_protected_checkpoint(
        client, evidence, "protectedResumeBefore", prior["surface"])
    project = _retained(client, config, evidence)
    client.bind_proof("project-lifecycle", {
        "kind": "retained-candidate-readback",
        "projectId": project.get("id"),
        "fingerprint": ((evidence.value["phases"].get("qc") or {})
                        .get("candidateFingerprint")),
    })
    evidence.phase("approval", _approve(client, config, evidence))
    repair_target = (evidence.value.get("preflight") or {}).get(
        "repairTargetId")
    if not isinstance(repair_target, str) or not repair_target:
        raise PalmierError(
            "resume evidence has no preflight-bound repair target")
    repair = _repair(client, config, repair_target)
    evidence.phase("repair", repair)
    with client.phase("manual-preservation"):
        manual = prove_manual_preservation(ManualProofInput(
            client, config.repo, config.out_dir, project,
            repair["elementId"]))
    client.bind_proof("manual-preservation", {
        "kind": "manual-preservation-readback",
        "manualFingerprint": manual["manualFingerprint"],
        "fork": manual["manualPreservingFork"],
    })
    evidence.phase("manualPreservation", manual)
    return prior, project
