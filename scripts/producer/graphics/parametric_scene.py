"""Closed parametric scene grammar compiled to a governed project bundle."""
from __future__ import annotations

import hashlib
import json
import os

from graphics.graphics_render import GSAP_CORE
from graphics.scene_bundle import BundleSnapshot, capture_bundle
from graphics.scene_bundle_manifest import AUTHORING_HYPERFRAMES_VERSION
from graphics.scene_contract import (
    SceneContractError,
    canonical_json,
    validate_scene,
)
from graphics.scene_lint import validate_scene_bundle

_GRAMMARS = {
    "split-cards": ("leftText", "rightText"),
    "stat-stack": ("title", "stat1", "stat2", "stat3"),
    "labeled-arrow": ("source", "label", "target"),
}
_OPTIONAL = {"accent", "accent2"}
_ROOT_KEYS = {
    "grammar", "sceneId", "timing", "canvas", "content", "renderMode",
    "provenance", "captionPolicy",
}


def _object(value: object, label: str, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise SceneContractError(f"{label} must have exactly {sorted(keys)}")
    return value


def _brief(value: object) -> dict:
    row = _object(value, "parametric brief", _ROOT_KEYS)
    grammar = row["grammar"]
    if grammar not in _GRAMMARS:
        raise SceneContractError(f"unsupported parametric grammar {grammar!r}")
    content = row["content"]
    required = set(_GRAMMARS[grammar])
    if not isinstance(content, dict) or not required <= set(content) \
            or set(content) - required - _OPTIONAL:
        raise SceneContractError("parametric content fields do not match grammar")
    for key in required:
        text = content[key]
        if not isinstance(text, str) or not text.strip() or len(text) > 160:
            raise SceneContractError(
                f"parametric content {key} must be 1..160 characters")
    for key in set(content) & _OPTIONAL:
        color = content[key]
        if not isinstance(color, str) or len(color) != 7 \
                or any(char not in "0123456789abcdefABCDEF"
                       for char in color[1:]) or color[0] != "#":
            raise SceneContractError(f"parametric color {key} must be #RRGGBB")
    if row["renderMode"] not in {"overlay-alpha", "takeover-opaque"}:
        raise SceneContractError("parametric renderMode is unsupported")
    return row


def _variable_rows(brief: dict) -> list[dict]:
    required = _GRAMMARS[brief["grammar"]]
    rows = [{
        "id": key, "type": "string", "required": True,
        "elementIds": ["parametric-content"], "maxLength": 160,
    } for key in required]
    for key in sorted(set(brief["content"]) & _OPTIONAL):
        rows.append({
            "id": key, "type": "color", "required": True,
            "elementIds": ["parametric-content"],
        })
    return rows


def _declared_variables(rows: list[dict]) -> str:
    values = [{
        "id": row["id"], "type": row["type"],
        "label": row["id"], "default": (
            "#054BC9" if row["type"] == "color" else row["id"]),
    } for row in rows]
    return json.dumps(values, separators=(",", ":"), ensure_ascii=True)


def _markup(grammar: str) -> str:
    if grammar == "split-cards":
        return '<section class="card" data-key="leftText"></section>' \
            '<section class="card" data-key="rightText"></section>'
    if grammar == "stat-stack":
        return '<h1 data-key="title"></h1><div class="stack">' + "".join(
            f'<div class="stat" data-key="stat{index}"></div>'
            for index in range(1, 4)) + "</div>"
    return '<div class="node" data-key="source"></div><div class="arrow">' \
        '<span data-key="label"></span></div>' \
        '<div class="node" data-key="target"></div>'


def _animation_event(brief: dict) -> list[dict]:
    frames = brief["timing"]["endFrameExclusive"] \
        - brief["timing"]["startFrame"]
    event_end = max(1, min(18, frames))
    return [{
        "eventId": "content-enter", "unitId": "unit-main",
        "elementId": "parametric-content", "property": "transform",
        "startFrame": 0, "endFrameExclusive": event_end,
        "easing": "power3.out",
    }]


def _variable_defaults(variables: list[dict]) -> dict:
    return {row["id"]: (
        "#054BC9" if row["type"] == "color" else row["id"])
        for row in variables}


def _html_head(canvas: dict, background: str) -> str:
    return f"""<!doctype html>
<html data-composition-variables='{{variables}}'>
<head><meta charset="UTF-8">
<meta name="viewport" content="width={canvas['width']}, height={canvas['height']}">
<link rel="stylesheet" href="/tokens.css">
<script src="/vendor/gsap/gsap.min.js"></script>
<style>
*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;overflow:hidden;
background:{background};font-family:var(--font);color:white}}
#root{{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
gap:4%;padding:7%}}.card,.node,.stat{{background:rgba(7,16,31,.88);
border:3px solid var(--accent,#054BC9);border-radius:28px;padding:32px;
font-size:clamp(28px,4vw,70px);font-weight:800;overflow-wrap:anywhere}}
.card{{width:44%;min-height:45%;display:grid;place-items:center;text-align:center}}
h1{{font-size:clamp(34px,5vw,84px)}}.stack{{display:grid;gap:20px;width:55%}}
.arrow{{font-size:clamp(24px,3vw,56px);min-width:18%;text-align:center}}
.arrow:after{{content:"  ➜";color:var(--accent2,#054BC9)}}
</style></head><body>"""


def _html_body(brief: dict, defaults: dict, event: list[dict],
               suffix: str) -> str:
    canvas = brief["canvas"]
    return f"""<main id="root" data-composition-id="parametric-{suffix}"
 data-width="{canvas['width']}" data-height="{canvas['height']}" data-duration="3">
{_markup(brief['grammar'])}</main>
<script>(function(){{"use strict";
const root=document.getElementById("root");const D=Number(root.dataset.duration);
const HF=window.__hyperframes;const vars=Object.assign(
{json.dumps(defaults, separators=(',', ':'), ensure_ascii=True)},
HF&&HF.getVariables?HF.getVariables():{{}});
root.style.setProperty("--accent",vars.accent||"#054BC9");
root.style.setProperty("--accent2",vars.accent2||"#054BC9");
root.querySelectorAll("[data-key]").forEach(function(node){{
node.textContent=String(vars[node.dataset.key]||"");}});
window.__sniperAnimationMap = {json.dumps(event, separators=(',', ':'))};
window.__timelines=window.__timelines||{{}};
const tl=gsap.timeline({{ paused: true }});
tl.fromTo(root,{{opacity:0,y:24}},{{opacity:1,y:0,duration:Math.min(.6,D)}});
tl.seek(0);window.__timelines["parametric-{suffix}"]=tl;}})();</script>
</body></html>"""


def _html(brief: dict, variables: list[dict], suffix: str) -> str:
    canvas = brief["canvas"]
    background = ("var(--module-canvas)"
                  if brief["renderMode"] == "takeover-opaque"
                  else "transparent")
    head = _html_head(canvas, background).replace(
        "{variables}", _declared_variables(variables))
    return head + "\n" + _html_body(
        brief, _variable_defaults(variables), _animation_event(brief), suffix)


def _manifest(brief: dict, variables: list[dict]) -> dict:
    timing = brief["timing"]
    return {
        "schemaVersion": 1,
        "bundleId": f"parametric-{brief['grammar']}",
        "fullEntry": "compositions/full.html",
        "unitEntries": {"unit-main": "compositions/unit-main.html"},
        "supportedCanvases": [brief["canvas"]],
        "supportedFps": [timing["fps"]],
        "variables": variables, "assetIds": [], "seed": 1,
        "runtime": {
            "hyperframesVersion": AUTHORING_HYPERFRAMES_VERSION,
            "gsapSha256": _file_sha256(GSAP_CORE),
        },
    }


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _scene(brief: dict, snapshot: BundleSnapshot) -> dict:
    variables = dict(brief["content"])
    exposed = list(_GRAMMARS[brief["grammar"]]) + sorted(
        set(variables) & _OPTIONAL)
    return {
        "schemaVersion": 1, "sceneId": brief["sceneId"], "version": 1,
        "timing": brief["timing"], "canvas": brief["canvas"],
        "renderMode": brief["renderMode"],
        "composition": {
            "type": "project", "bundleId": snapshot.manifest["bundleId"],
            "bundleHash": snapshot.digest,
            "entry": snapshot.manifest["fullEntry"], "variables": variables,
        },
        "elements": [{
            "elementId": "parametric-content", "role": brief["grammar"],
            "exposedProperties": exposed, "values": variables,
        }],
        "renderUnits": [{
            "unitId": "unit-main", "elementIds": ["parametric-content"],
            "zIndex": 0, "entry": "compositions/unit-main.html",
            "compositeMode": "normal", "palmierGranularity": "unit",
        }],
        "captionPolicy": brief["captionPolicy"], "dependencies": [],
        "provenance": brief["provenance"],
    }


def compile_parametric_scene(value: object,
                             attempt_root: str) -> tuple[dict, BundleSnapshot]:
    """Compile a closed brief into an immutable, linted scene bundle."""
    brief = _brief(value)
    if os.path.lexists(attempt_root):
        raise SceneContractError("parametric attempt root must not exist")
    os.makedirs(attempt_root, mode=0o700)
    variables = _variable_rows(brief)
    manifest = _manifest(brief, variables)
    _write(os.path.join(attempt_root, "bundle.json"),
           canonical_json(manifest))
    for name in ("full", "unit-main"):
        _write(os.path.join(attempt_root, "compositions", f"{name}.html"),
               _html(brief, variables, name).encode("utf-8"))
    snapshot = capture_bundle(os.path.realpath(attempt_root))
    scene = validate_scene(_scene(brief, snapshot))
    validate_scene_bundle(scene, snapshot)
    return scene, snapshot
