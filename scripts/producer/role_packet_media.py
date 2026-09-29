"""Resolve moving previews and checked exports into frozen review media, events and coverage."""
from __future__ import annotations

from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path

from role_packet_files import (MAX_RECEIPT_JSON, ArtifactError, artifact, canonical_directory,
                               canonical_file, linked_media, read_json)
from role_packet_native import previous_records, project_subject, seconds, suppression_rows

PREVIEW_STATUS = "native-motion-previews-complete"
CHECKED_STATUS = "native-short-checked-for-review"
PREVIEW_RECEIPTS = ("preview.render.json", "export-request.json", "delivery.json", "capture.render.json",
                    "native-frames.json", "prepared-audio.json", "audio-preparation/receipt.json")
EXPORT_RECEIPTS = ("export-request.json", "render-stage.json", "capture-stage.json", "checks.json",
                   "pipeline.render.json", "verification.render.json", "audio/receipt.json", "native-frames.json")


VOID_TAGS = {"meta", "link", "img", "input", "br", "hr", "source", "area", "base", "embed", "wbr", "param", "track", "col"}


class Mounts(HTMLParser):
    """Collect composition mounts; a mount inside a timed parent keeps a relative clock."""

    def __init__(self) -> None:
        """Start with no mounts and an empty open-element stack."""
        super().__init__()
        self.rows: list[dict] = []
        self.timed: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Record a mount and whether any open ancestor carries its own start time."""
        values = dict(attrs)
        if "data-composition-src" in values:
            self.rows.append({**values, "nested": any(timed for _tag, timed in self.timed)})
        if tag not in VOID_TAGS:
            self.timed.append((tag, values.get("data-start") not in (None, "0")))

    def handle_endtag(self, tag: str) -> None:
        """Close the innermost matching open element."""
        for index in range(len(self.timed) - 1, -1, -1):
            if self.timed[index][0] == tag:
                del self.timed[index:]
                return


def receipt_rows(directory: Path, names: tuple[str, ...], label: str) -> list[dict]:
    """Existing attempt receipts, each strictly hashed."""
    return [artifact(f"{label}:{name}", directory / name, f"{label} receipt {name}.")
            for name in names if (directory / name).is_file()]


def clip_rows(value: dict, label: str) -> list[dict]:
    """Each moving-preview clip, which must still match the hash its record declares."""
    rows = []
    for index, clip in enumerate(value["clips"]):
        row = artifact(f"{label}:clip-{index}", clip["path"], f"{label} moving-preview clip {index}.")
        if row["sha256"] != clip["sha256"]:
            raise ArtifactError(f"{row['path']} changed after its preview record was sealed")
        rows.append(row)
    return rows


def validated_chain(preview: Path, project: str) -> list:
    """Reuse the exporter's own completed-owner and ancestor validation."""
    from studio.native_preview_history import preview_chain
    try:
        return preview_chain(preview, project)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as error:
        raise ArtifactError(f"{preview} is not a completed, unchanged moving-preview chain: {error}") from error


def windows(value: dict, rate: Fraction) -> list[dict]:
    """The continuous windows a motion critic must play, with exact frame/time bounds.

    Paths are canonical real paths, the same ones clip_rows freezes, so typed inspection names one path per clip.
    """
    return [{"index": index, "startFrame": clip["startFrame"], "endFrameExclusive": clip["endFrameExclusive"],
             "startSeconds": seconds(clip["startFrame"], rate), "endSeconds": seconds(clip["endFrameExclusive"], rate),
             "path": str(canonical_file(clip["path"])), "sha256": clip["sha256"]} for index, clip in enumerate(value["clips"])]


def uncovered(total: int, spans: list[tuple[int, int]] | None, rate: Fraction) -> list[dict] | None:
    """Program intervals that no moving-preview window showed; None when coverage is unknown."""
    if spans is None:
        return None
    rows, cursor = [], 0
    for start, end in sorted(spans):
        if start > cursor:
            rows.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total:
        rows.append((cursor, total))
    return [{"startFrame": start, "endFrameExclusive": end, "startSeconds": seconds(start, rate),
             "endSeconds": seconds(end, rate)} for start, end in rows]


def mount_events(project: Path, rate: Fraction, total: int) -> tuple[list[tuple[int, str]], list[str]]:
    """Entrance/end frames of root-clock mounts; nested mounts are named with no invented clock."""
    parser = Mounts()
    parser.feed((project / "index.html").read_text(encoding="utf-8"))
    events = []
    for row in (row for row in parser.rows if not row["nested"]):
        start = Fraction(row.get("data-start", "0"))
        end = start + Fraction(row.get("data-duration", "0"))
        name = row["data-composition-src"]
        first, last = (max(0, min(total - 1, round(value * rate))) for value in (start, end))
        events += [(first, f"{name} mount starts"), (last, f"{name} mount ends")]
    return events, [row["data-composition-src"] for row in parser.rows if row["nested"]]


def covered(frame: int, spans: list[tuple[int, int]] | None) -> bool | None:
    """Whether any preview window showed the frame; None when preview evidence is unavailable."""
    return None if spans is None else any(start <= frame < end for start, end in spans)


def program_events(plan: dict, project: Path, rate: Fraction, spans: list[tuple[int, int]] | None) -> dict:
    """Joins, scene changes, crop changes, graphic mounts and the ending, merged by frame."""
    canvas, labels = plan["canvas"], {}
    total = canvas["totalFrames"]
    rows = [(row["startFrame"], "source join") for row in canvas.get("segments", []) if row["startFrame"] > 0]
    rows += [(scene["startFrame"], "scene change") for scene in plan["strategy"].get("scenes", []) if scene["startFrame"] > 0]
    views = canvas.get("pictureViews", [])
    rows += [(view["startFrame"], "picture view change") for previous, view in zip(views, views[1:])
             if view.get("crop") != previous.get("crop") or view.get("box") != previous.get("box")]
    for window in suppression_rows(plan):
        rows += [(window["startFrame"], "caption suppression starts")]
        rows += [(window["endFrame"], "caption suppression ends")] if window["endFrame"] < total else []
    mounts, nested = mount_events(project, rate, total)
    for frame, label in rows + mounts + [(total - 1, "final frame")]:
        labels.setdefault(frame, []).append(label)
    events = [{"frame": frame, "seconds": seconds(frame, rate), "labels": sorted(set(names)),
               "coveredByPreview": covered(frame, spans)} for frame, names in sorted(labels.items())]
    return {"events": events, "nestedMounts": nested}


def capture_summary(frames_file: Path) -> dict:
    """Native capture status, reverse-seek repeats and the frame-to-still map critics look up."""
    value = read_json(frames_file, MAX_RECEIPT_JSON)
    rows = value.get("frames", [])
    repeats = [row for row in rows if row.get("repeat")]
    stills: dict[str, str] = {}
    for row in rows:
        stills.setdefault(str(row["frame"]), Path(row["path"]).name)
    return {"status": value.get("status"), "failedSceneStates": len(value.get("failedSceneStates") or []),
            "capturedFrames": len(rows), "reverseRepeats": len(repeats),
            "reverseByteIdentical": sum(row.get("byteIdentical") is True for row in repeats),
            "stills": stills,
            "stillsDirectory": str(Path(rows[0]["path"]).parent) if rows else None,
            "note": "Stills are exact native states, not motion; non-byte-identical reverse repeats still need the "
                    "exporter's pixel gate."}


def preview_subject(preview_file: str | Path) -> dict:
    """A completed moving preview, its ancestors, project, windows, coverage and events."""
    file = canonical_file(preview_file)
    value = read_json(file)
    if value.get("status") != PREVIEW_STATUS:
        raise ArtifactError(f"{file} is not a completed moving-preview record")
    project_path = read_json(file.parent / "export-request.json")["project"]
    chain = validated_chain(file, project_path)
    project = project_subject(project_path)
    rows = [artifact("preview:motion-previews.json", file, "The moving-preview record under review.")]
    rows += receipt_rows(file.parent, PREVIEW_RECEIPTS, "preview") + clip_rows(value, "preview")
    for depth, (ancestor, prior) in enumerate(chain[1:], start=1):
        rows += [artifact(f"ancestor-{depth}:motion-previews.json", ancestor, "Retained ancestor preview.")]
        rows += clip_rows(prior, f"ancestor-{depth}")
    spans = [(clip["startFrame"], clip["endFrameExclusive"]) for _file, item in chain for clip in item["clips"]]
    rate, plan = project["rate"], project["plan"]
    subject = {**project["subject"], "preview": {"path": str(file), "sha256": rows[0]["sha256"]},
               "windows": windows(value, rate), "units": value["packet"]["units"],
               "changedUnits": value.get("changedUnits"), "reusedUnits": value.get("reusedUnits"),
               "uncovered": uncovered(plan["canvas"]["totalFrames"], spans, rate),
               **program_events(plan, project["project"], rate, spans)}
    if (file.parent / "native-frames.json").is_file():
        subject["capture"] = capture_summary(file.parent / "native-frames.json")
    earlier = previous_records(Path(project_path).parent, ("MOTION-REVIEW",))
    return {"artifacts": rows + project["artifacts"] + earlier, "declaredMedia": [], "authors": project["authors"],
            "subject": subject, "packet": value["packet"], "spans": spans, "plan": plan, "features": project["features"]}


def checked_delivery(directory: Path) -> tuple[dict, dict]:
    """Require a checked-for-review delivery whose MP4 still matches its recorded hash."""
    delivery = read_json(directory / "delivery.json")
    if delivery.get("status") != CHECKED_STATUS:
        raise ArtifactError(f"{directory} is not a checked native Short delivery (status {delivery.get('status')!r})")
    video = linked_media("export:video", delivery["output"], "The checked MP4 under final review.")
    if Path(video["path"]).parent != directory or video["sha256"] != delivery.get("sha256"):
        raise ArtifactError(f"{video['path']} is outside the export or changed after delivery QC")
    return delivery, video


def export_preview(request: dict) -> dict:
    """The export's admitted preview chain, or an explicit statement that its evidence is unavailable."""
    if not request.get("previewFrom"):
        return {"coverage": {"status": "none-recorded"}, "artifacts": [], "spans": [], "windows": []}
    try:
        preview = preview_subject(request["previewFrom"])
    except ArtifactError as error:
        return {"coverage": {"status": "unavailable", "reason": str(error)[:600]}, "artifacts": [], "spans": None,
                "windows": []}
    return {"coverage": {"status": "available", "path": preview["subject"]["preview"]["path"]},
            "artifacts": preview["artifacts"], "spans": preview["spans"], "windows": preview["subject"]["windows"]}


def export_reviews(request: dict) -> tuple[list[dict], dict]:
    """The motion reviews that admitted this render, when they are still present and unchanged."""
    if not request.get("previewReviews"):
        return [], {"status": "none-recorded"}
    try:
        row = artifact("export:preview-reviews", request["previewReviews"], "Motion reviews that admitted this render.")
    except ArtifactError as error:
        return [], {"status": "unavailable", "reason": str(error)[:600]}
    return [row], {"status": "available", "path": row["path"]}


def export_subject(export_dir: str | Path) -> dict:
    """A checked export with its project, preview coverage, events and audio review rows."""
    directory = canonical_directory(export_dir)
    delivery, video = checked_delivery(directory)
    request = read_json(directory / "export-request.json")
    project = project_subject(request["project"])
    rows = [artifact("export:delivery.json", directory / "delivery.json", "Checked delivery receipt."), video]
    preview, (reviews, review_status) = export_preview(request), export_reviews(request)
    rows += receipt_rows(directory, EXPORT_RECEIPTS, "export") + preview["artifacts"] + reviews
    rate, plan, spans = project["rate"], project["plan"], preview["spans"]
    subject = {**project["subject"], "export": {"directory": str(directory),
               "delivery": {"path": rows[0]["path"], "sha256": rows[0]["sha256"], "status": delivery["status"]},
               "video": {key: video[key] for key in ("path", "sha256", "bytes", "links")}},
               "audioReview": [row for row in delivery.get("audioQuality", []) if row.get("status") != "pass"],
               "audioReviewRequired": delivery.get("audioReviewRequired"), "humanApproved": delivery.get("humanApproved"),
               "previewCoverage": preview["coverage"], "previewReviews": review_status,
               "previewWindows": preview["windows"], "uncovered": uncovered(plan["canvas"]["totalFrames"], spans, rate),
               **program_events(plan, project["project"], rate, spans)}
    earlier = previous_records(directory.parent, ("FINAL-REVIEW", "MOTION-REVIEW"))
    return {"artifacts": rows + project["artifacts"] + earlier, "declaredMedia": [], "authors": project["authors"],
            "subject": subject, "plan": plan, "features": project["features"]}
