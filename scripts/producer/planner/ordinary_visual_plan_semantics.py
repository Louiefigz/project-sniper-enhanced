"""Exact modality semantics for ordinary visual-plan execution."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable

from planner.visual_plan_fields import canonical_hash

ErrorSink = Callable[[str], None]


@dataclass(frozen=True)
class StyleMappingContext:
    """One graphic and the selected candidate composition it may claim."""

    plan: dict
    graphic: dict
    composition: dict
    label: str


@dataclass(frozen=True)
class ExecutionBindingContext:
    """Controller facts and resolved edit-plan rows for one selected candidate."""

    plan: dict
    decision: dict
    opportunity: dict
    candidate: dict
    records: dict
    fps: float
    elements: list[dict]
    label: str


def _expected_project(raw: str, error: ErrorSink) -> dict | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        error("controller expected project authority is invalid JSON")
        return None
    if not isinstance(value, dict):
        error("controller expected project authority is not an object")
        return None
    return value


def check_expected_authority(
    visual: dict,
    expected: tuple[str | None, str | None, str | None],
    error: ErrorSink,
) -> None:
    """Reject self-declared project or catalog identities."""
    project_json, catalog_hash, controller_hash = expected
    expected = _expected_project(project_json, error) if project_json is not None else None
    if expected is not None and visual["project"] != expected:
        error("VISUAL-PLAN.json project authority differs from controller context")
    if catalog_hash is not None \
            and canonical_hash(visual["catalogPin"]) != catalog_hash:
        error("VISUAL-PLAN.json catalogPin differs from controller context")
    controller = {key: visual[key] for key in (
        "transcriptAuthority", "mediaAuthority", "relatedUsageAuthority",
        "relatedUsage")}
    if controller_hash is not None and canonical_hash(controller) != controller_hash:
        error("VISUAL-PLAN.json transcript, media, or related-usage authority differs from controller context")


def check_style_mapping(context: StyleMappingContext, error: ErrorSink) -> None:
    """Cross-check mapped style prose against the selected candidate."""
    application = context.plan.get("styleApplication")
    if application is None:
        return
    if not isinstance(application, dict):
        error(f"{context.label} cannot bind malformed styleApplication")
        return
    graphic_id = context.graphic.get("id")
    rows = []
    for field in ("choices", "supplementalChoices"):
        choices = application.get(field, [])
        if isinstance(choices, list):
            rows.extend(row for row in choices if isinstance(row, dict)
                        and row.get("graphicId") == graphic_id)
    if not isinstance(graphic_id, str) or not graphic_id or not rows:
        return
    if len(rows) != 1:
        error(f"{context.label} maps to multiple styleApplication choices")
        return
    for field in ("anatomy", "development"):
        if rows[0].get(field) != context.composition.get(field):
            error(
                f"{context.label} styleApplication {field} differs from selected candidate")


def _catalog_kind(candidate: dict, records: dict, label: str,
                  error: ErrorSink) -> str | None:
    source = candidate.get("source")
    record_id = source.get("recordId") if isinstance(source, dict) else None
    record = records.get(record_id) if isinstance(record_id, str) else None
    integration = record.get("integration") if isinstance(record, dict) else None
    kind = integration.get("kind") if isinstance(integration, dict) else None
    if not isinstance(kind, str) or not kind:
        error(f"{label} selected catalog record has no ordinary adapter kind")
        return None
    return kind


def _ref(element: dict) -> dict:
    return {"lane": element["lane"], "index": element["index"]}


def _range(start: int, end: int) -> dict:
    return {"startFrame": start, "endFrameExclusive": end}


def _one(context: ExecutionBindingContext, lane: str,
         error: ErrorSink) -> dict | None:
    if len(context.elements) != 1 or context.elements[0]["lane"] != lane:
        error(f"{context.label}: selected modality requires one exact {lane} element")
        return None
    return context.elements[0]


def _output_range(context: ExecutionBindingContext) -> dict:
    timing = context.opportunity["timing"]
    return _range(timing["startFrame"], timing["endFrameExclusive"])


def _row_range(context: ExecutionBindingContext, element: dict) -> dict | None:
    row, lane = element["row"], element["lane"]
    if lane == "cutTrack":
        start, end = row.get("start"), row.get("end")
    else:
        start = row.get("assetStart")
        duration = row.get("outEnd", 0) - row.get("outStart", 0) \
            if all(isinstance(row.get(key), (int, float))
                   for key in ("outStart", "outEnd")) else None
        end = start + duration if isinstance(start, (int, float)) \
            and isinstance(duration, (int, float)) else None
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           for value in (start, end)):
        return None
    return _range(round(float(start) * context.fps),
                  round(float(end) * context.fps))


def _source_hash(source: dict) -> object:
    return source.get("sourceSha256", source.get("sha256"))


def _catalog_binding(context: ExecutionBindingContext,
                     error: ErrorSink) -> dict | None:
    element = _one(context, "graphicsTrack", error)
    kind = _catalog_kind(context.candidate, context.records,
                         context.label, error)
    source = context.candidate.get("source") or {}
    if element is None or kind is None:
        return None
    row, mount_id = element["row"], element["row"].get("id")
    if row.get("kind") != kind or not isinstance(mount_id, str) or not mount_id:
        error(f"{context.label}: catalog mount differs from selected adapter")
        return None
    return {"kind": "catalog", "element": _ref(element), "mountId": mount_id,
            "catalogId": source.get("recordId"),
            "sourceSha256": _source_hash(source), "adapterKind": kind,
            "implementationSha256": canonical_hash(row)}


def _media_binding(context: ExecutionBindingContext,
                   error: ErrorSink) -> dict | None:
    lane = "cutTrack" if context.candidate["modality"] == "source-footage" \
        else "brollTrack"
    element = _one(context, lane, error)
    source = context.candidate.get("source")
    if element is None or not isinstance(source, dict):
        error(f"{context.label}: selected media lacks admitted source authority")
        return None
    source_range = source.get("range")
    actual_range = _row_range(context, element)
    asset_id = element["row"].get(
        "sourceId" if lane == "cutTrack" else "assetId")
    if not isinstance(source_range, dict) or actual_range != source_range \
            or asset_id != source.get("recordId"):
        error(f"{context.label}: media source identity or range differs from candidate")
        return None
    return {"kind": "media", "element": _ref(element), "assetId": asset_id,
            "sourceSha256": _source_hash(source), "sourceRange": actual_range,
            "outputRange": _output_range(context),
            "implementationSha256": canonical_hash(element["row"])}


_VISIBLE_KEYS = frozenset(("text", "title", "label", "value", "headline",
                           "subhead", "body", "copy", "caption", "statement"))


def _visible_text(value: object, active: bool = False) -> list[str]:
    if isinstance(value, str):
        return [value] if active and value else []
    if isinstance(value, list):
        return [text for item in value for text in _visible_text(item, active)]
    if not isinstance(value, dict):
        return []
    return [text for key, item in value.items()
            for text in _visible_text(item, active or key in _VISIBLE_KEYS)]


def _text_binding(context: ExecutionBindingContext,
                  error: ErrorSink) -> dict | None:
    element = _one(context, "graphicsTrack", error)
    if element is None:
        return None
    row, texts = element["row"], _visible_text(element["row"])
    visible_id = row.get("id")
    if not isinstance(visible_id, str) or not visible_id or not texts:
        error(f"{context.label}: text execution lacks exact visible content")
        return None
    content = {"visibleId": visible_id, "kind": row.get("kind"),
               "visibleText": texts, "spec": row.get("spec")}
    return {"kind": "text", "element": _ref(element), "visibleId": visible_id,
            "visibleText": texts, "contentSha256": canonical_hash(content)}


def _transition_binding(context: ExecutionBindingContext,
                        error: ErrorSink) -> dict | None:
    element = _one(context, "transitions", error)
    if element is None:
        return None
    row = element["row"]
    identifier, mechanism, at = row.get("id"), row.get("kind"), row.get("outTime")
    if not all(isinstance(value, str) and value for value in (identifier, mechanism)) \
            or isinstance(at, bool) or not isinstance(at, (int, float)):
        error(f"{context.label}: transition lacks an exact mechanism, ID, or time")
        return None
    return {"kind": "transition", "element": _ref(element),
            "transitionId": identifier, "mechanism": mechanism,
            "atFrame": round(float(at) * context.fps),
            "configurationSha256": canonical_hash(row)}


def _custom_binding(context: ExecutionBindingContext,
                    error: ErrorSink) -> dict | None:
    pins = {(row.get("path"), row.get("sha256"))
            for row in context.candidate.get("dependencyPins", [])
            if isinstance(row, dict)}
    bindings = []
    for element in context.elements:
        row = element["row"]
        spec = row.get("spec") if isinstance(row.get("spec"), dict) else {}
        path = row.get("implementationPath", spec.get("implementationPath"))
        digest = row.get("implementationSha256", spec.get("implementationSha256"))
        visible_id = row.get("id")
        if not isinstance(visible_id, str) or (path, digest) not in pins:
            error(f"{context.label}: custom-native element lacks pinned implementation bytes")
            return None
        bindings.append({"element": _ref(element), "visibleId": visible_id,
                         "implementationPath": path, "implementationSha256": digest,
                         "rowSha256": canonical_hash(row)})
    return {"kind": "custom-native", "elements": bindings}


def _presenter_binding(context: ExecutionBindingContext,
                       error: ErrorSink) -> dict | None:
    element = _one(context, "cutTrack", error)
    if element is None:
        return None
    row_range = _row_range(context, element)
    source_id = element["row"].get("sourceId")
    if row_range is None or not isinstance(source_id, str) or not source_id:
        error(f"{context.label}: presenter hold lacks an exact source scene")
        return None
    return {"kind": "presenter", "element": _ref(element),
            "sourceId": source_id, "sourceRange": row_range,
            "outputRange": _output_range(context),
            "implementationSha256": canonical_hash(element["row"])}


def check_execution_binding(context: ExecutionBindingContext,
                            error: ErrorSink) -> None:
    """Compare the authored binding with facts derived from executable rows."""
    modality = context.candidate["modality"]
    builders = {"catalog": _catalog_binding, "text": _text_binding,
                "transition": _transition_binding,
                "custom-native": _custom_binding, "presenter": _presenter_binding,
                "source-footage": _media_binding, "supplied-broll": _media_binding,
                "external-media": _media_binding}
    if modality == "omit":
        expected = {"kind": "omit"}
    else:
        builder = builders.get(modality)
        expected = builder(context, error) if builder is not None else None
    if expected is not None and context.decision.get("binding") != expected:
        error(f"{context.label}: execution binding differs from executable {modality} facts")
