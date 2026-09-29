"""Exact typed submission commands, observation drafts and owner steps for role packets."""
from __future__ import annotations

import shlex
from pathlib import Path

from role_packet_catalog import OBSERVATION_KIND, SUBMIT_OPERATION
from role_packet_files import next_sibling

REVIEW_CLI = "scripts/producer/native-review.ts"
COVERAGE = ("briefAndRetainedMessage", "assetsAndSourceEvidence", "cuesAndSceneCoverage", "layoutCropAndText",
            "motionAndTransitions", "pacingAndAudio", "feasibility", "visualSourceSelection")
LAUNCHER = "./sniper on macOS or sniper.cmd on Windows, from the Sniper folder"
UNTRACKED = "not tracked by this packet"
OBSERVATION_SCHEMA = 2
INSPECTION_KINDS = ("still-frames", "motion-playback", "audio-listening")
INSPECTION_RULE = (
    "Record what you actually did as typed inspection entries, each naming the exact artifact path and sha256 you "
    "covered: still-frames (samples = the exact frames looked at, ascending: program frames of a target below, "
    "seconds of any other artifact, [0] for an image), motion-playback (continuous normal-speed playback of the "
    "moving picture) or audio-listening (hearing the actual audio at normal speed). span is \"whole\" or "
    "{\"frames\": [start, endExclusive]} on a target, \"whole\" or {\"seconds\": [start, end]} elsewhere. "
    "Stills cover only their sampled frames: they are reported as a sampled picture review, never every frame, and "
    "exhaustive stills are not required. approves lists what a pass approves: picture needs frames looked at on "
    "every target, motion needs playback of every target frame and audio needs listening to every target frame. "
    "Still frames never establish motion; decode, loudness and sample checks are not listening. A revise or block "
    "verdict and a plan review approve nothing (approves: []). The helper refuses unbacked approvals, other bytes "
    "than the target's, notes, events or located issues at frames nobody looked at or heard, and playback plus "
    "listening, summed over artifacts, longer than the time since this packet was resolved. A subject departing "
    "from the operator's given title or script is a material issue scoped approved-content-contradiction; a "
    "proposed change to the given words is a finding scoped proposed-change (surfaced for the operator, never "
    "withholding approval). All typed evidence is declared, not authenticated.")


def command(argv: list[str]) -> dict:
    """One launcher command, shell-quoted for macOS plus the raw arguments for Windows."""
    return {"shell": "./sniper " + " ".join(shlex.quote(part) for part in argv), "argv": argv, "launcher": LAUNCHER}


def inspection_targets(role: str, subject: dict) -> list[dict]:
    """Renderings whose every frame an approval must cover: preview windows or the checked MP4."""
    if role == "motion-critic":
        return [{"path": row["path"], "sha256": row["sha256"], "frames": [row["startFrame"], row["endFrameExclusive"]]}
                for row in subject["windows"]]
    if role == "final-critic":
        video = subject["export"]["video"]
        return [{"path": video["path"], "sha256": video["sha256"], "frames": [0, subject["totalFrames"]]}]
    return []


def critic_submission(role: str, paths: dict, subject: dict) -> dict:
    """The exact command a critic runs after writing its observations; never run by the packet."""
    argv = ["node", "--import", "tsx", REVIEW_CLI, SUBMIT_OPERATION[role],
            str(paths["packet"]), str(paths["observations"]), str(paths["record"])]
    return {**command(argv), "packet": str(paths["packet"]), "observations": str(paths["observations"]),
            "record": str(paths["record"]),
            "rule": "Write every observation, verdict and limitation yourself in the observations file, then run this. "
                    "The helper binds hashes and canonical paths; it refuses stale inputs and never supplies a verdict.",
            "inspection": {"kinds": list(INSPECTION_KINDS), "targets": inspection_targets(role, subject),
                           "rule": INSPECTION_RULE}}


def reviewer_draft(authors: list[str]) -> dict:
    """Identity fields stay empty except a single recorded author identity."""
    return {"identity": None, "sessionId": None,
            "plannerSessionId": authors[0] if len(set(authors)) == 1 else None, "independent": None}


def observation_draft(role: str, packet_sha256: str, subject: dict, authors: list[str]) -> dict:
    """A structure-only draft: every judgment field is null or empty and must be authored.

    Nothing about inspection is prefilled: an entry exists only when the critic records what it actually did.
    """
    draft = {"schemaVersion": OBSERVATION_SCHEMA, "kind": OBSERVATION_KIND[role], "rolePacketSha256": packet_sha256,
             "reviewer": reviewer_draft(authors), "coverage": {key: None for key in COVERAGE},
             "verdict": None, "summary": None, "materialIssues": [], "findings": [], "limitations": [],
             "evidence": [], "inspection": [], "approves": []}
    if role == "plan-critic":
        draft["scenes"] = [{"index": row["index"], "startFrame": row["startFrame"], "endFrame": row["endFrame"],
                            "note": None} for row in subject["scenes"]]
        return draft
    draft["assessment"] = None
    if role == "motion-critic":
        draft["windows"] = [{"startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"],
                             "observations": []} for row in subject["windows"]]
        return draft
    draft["frameNotes"] = []
    draft["events"] = [{"frame": row["frame"], "note": None} for row in subject["events"]]
    return draft


def step(identifier: str, argv: list[str], note: str, state: str = UNTRACKED) -> dict:
    """One owner route step."""
    return {"id": identifier, "state": state, "command": command(argv), "note": note}


def owner_steps(subject: dict, clip_dir: Path, author: str | None) -> list[dict]:
    """Ordered native-Short route with known paths; new outputs are proposed unused siblings."""
    plan, project = subject.get("plan"), subject.get("project")
    preview, export = subject.get("preview"), subject.get("export")
    session = ["--author-session", author] if author else []
    project_dir = project["project"] if project else str(next_sibling(clip_dir, "native"))
    preview_file = preview["preview"]["path"] if preview else "<new preview attempt>/motion-previews.json"
    export_dir = export["export"]["directory"] if export else str(next_sibling(clip_dir, "final"))
    return [*plan_steps(plan, session, clip_dir), *build_steps(plan, project, project_dir, clip_dir),
            step("preview-export", ["python3", "scripts/producer/studio/native_export.py", project_dir,
                 str(next_sibling(clip_dir, "preview")), "--preview-only"],
                 "Stops at continuous moving previews; never full-picture authority.",
                 "done" if preview else "pending"),
            step("motion-review", ["python3", "-B", "scripts/producer/context.py", "--role", "motion-critic",
                 "--preview", preview_file, *session], "A fresh critic reviews the written packet and finishes "
                 "with its typed submission (submit-motion)."),
            step("final-export", ["python3", "scripts/producer/studio/native_export.py", project_dir, export_dir,
                 "--preview-reviews", "<MOTION-REVIEW record from submit-motion>"],
                 "Requires a passing, current motion review record.", "done" if export else "pending"),
            step("final-review", ["python3", "-B", "scripts/producer/context.py", "--role", "final-critic",
                 "--export", export_dir, *session], "Independent full-playback review of the exact checked MP4."),
            step("handoff-studio", ["python3", "scripts/producer/studio/managed_preview.py", "open", project_dir],
                 "Open with the checked MP4 review; both views are required for the handoff.")]


def plan_steps(plan: dict | None, session: list[str], clip_dir: Path) -> list[dict]:
    """Freeze the request, then independent plan review bound into a new plan file."""
    if not plan:
        return [step("prepare-request", ["node", "--import", "tsx", "scripts/producer/native-short.ts", "prepare",
                     "<job>/producer"], "Freeze the stored intent; author the plan from the returned request. A per-clip "
                     "producer folder adds --manifest <canonical admitted asset_manifest.json>.", "pending")]
    bound = plan.get("boundPrebuildReview") or {}
    state = "done" if bound.get("current") and bound.get("verdict") == "pass" else "pending"
    return [step("plan-review", ["python3", "-B", "scripts/producer/context.py", "--role", "plan-critic", "--plan",
                 plan["plan"]["path"], *session], "A fresh critic that did not author the plan reviews it.", state),
            step("bind-plan-review", ["node", "--import", "tsx", REVIEW_CLI, "bind-prebuild", plan["plan"]["path"],
                 "<PREBUILD-REVIEW record from submit-prebuild>", str(next_sibling(clip_dir, "native-plan", ".json"))],
                 "Writes a new plan file carrying the verified prebuildReview binding.", state)]


def build_steps(plan: dict | None, project: dict | None, project_dir: str, clip_dir: Path) -> list[dict]:
    """Build the staged project, then the early static preflight on those exact files."""
    built = bool(plan and project and project.get("planHash") == plan["plan"]["planHash"])
    plan_file = plan["plan"]["path"] if plan else "<plan.json with a current prebuildReview>"
    return [step("build", ["node", "--import", "tsx", "scripts/producer/native-short.ts", "build", plan_file,
                 project_dir], "Refuses a missing, failed or stale prebuild review.", "done" if built else "pending"),
            step("early-preflight", ["python3", "-B", "scripts/producer/studio/native_preflight.py", project_dir,
                 "--output-dir", str(next_sibling(clip_dir, "static"))], "Run after every build, before any "
                 "preview or export (docs/producer/NATIVE_PREFLIGHT.md); static-checks-pass is never render approval.")]
