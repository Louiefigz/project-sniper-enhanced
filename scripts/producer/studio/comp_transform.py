"""Transform a registered motion comp into a Studio review sub-composition.

Source comps under ``templates/motion/compositions/`` are standalone full
documents; Studio's mount contract clones ONLY ``<template>`` contents into
the host slot and discards the entire ``<head>`` (vendored docs:
``hyperframes-core/references/sub-compositions.md``). This module rewrites one
source comp into a per-instance file whose functional payload lives inside
``<template>``, with the composition id made unique per instance in BOTH the
root tag and the ``window.__timelines[...]`` registration (a mismatch stalls
the runtime 45s per scene).
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from graphics.composition_transform import set_root_duration
from graphics.template_contract import declared_variables
from studio import StudioProjectError
from studio.comp_dependencies import bind_instance_styles, bind_mounted_duration, inline_local_body_scripts

_HEAD_RE = re.compile(r"<head[^>]*>(?P<inner>.*?)</head>", re.DOTALL | re.IGNORECASE)
_BODY_RE = re.compile(r"<body[^>]*>(?P<inner>.*?)</body>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_ROOT_TAG_RE = re.compile(r'<[^>]*data-composition-id="[^"]*"[^>]*>')
_ROOT_ID_RE = re.compile(r'\bid="([^"]*)"')
# Rules whose whole selector list is html/body target the standalone page
# canvas; inside the mounted slot no html/body exists, so retarget them onto
# the comp's root element (keeps font inheritance + canvas clipping).
_PAGE_RULE_RE = re.compile(
    r"(?P<lead>\A|[{};>])(?P<gap>\s*)(?:html|body)(?:\s*,\s*(?:html|body))*\s*\{")
_PAGE_LEFTOVER_RE = re.compile(r"(?:\A|[{};,>])\s*(?:html|body)\b(?!-)")

_INSTANCE_SHELL = """<!doctype html>
<html lang="en" data-composition-variables='{declarations}'>
  <head>
    <meta charset="UTF-8" />
    <title>{instance_id}</title>
    <link rel="stylesheet" href="../assets/tokens.css" />
    <script src="../assets/vendor/gsap.min.js"></script>
{extra_head}  </head>
  <body>
    <template>
<script>if (typeof gsap === "undefined") throw new Error("{instance_id}: gsap must be loaded by the host page head"); /* inlined: gsap runtime supplied by the host */</script>
<script>if (typeof __hfCompId === "undefined") window.__hfVariables = Object.assign({standalone_vars}, window.__hfVariables || {{}}); /* Studio's standalone per-comp preview synthesizes a page WITHOUT the html declarations attr, so getVariables() would fall back to comp-internal defaults (verified live: default icons 404). Seed the runtime's page-level variable channel with this instance's values. In the host player every template script runs inside the scoped mount wrapper (which defines __hfCompId), so this is a no-op there. */</script>
{styles}
{body}
    </template>
  </body>
</html>
"""

_SCALAR_TYPES = {"string": str, "color": str, "boolean": bool}


@dataclass(frozen=True)
class SourceComp:
    """Parsed pieces of one registered composition file."""

    kind: str
    styles: str
    body: str
    root_el_id: str
    variables: dict[str, dict]
    uses_split_text: bool
    uses_motion_tokens: bool
    bind_duration: bool = True


@dataclass(frozen=True)
class InstancePlan:
    """What one graphicsTrack entry contributes to its instance file."""

    instance_id: str
    spec: dict
    duration: float


@dataclass(frozen=True)
class InstanceBuild:
    """A finished instance file plus its panel-editability report."""

    instance_id: str
    html: str
    non_panel_keys: tuple[str, ...]


def parse_source_comp(kind: str, comp_html: str, scope_styles: bool = False,
                      bind_duration: bool = True) -> SourceComp:
    """Split one source comp into head styles, body payload and metadata."""
    head = _HEAD_RE.search(comp_html)
    body = _BODY_RE.search(comp_html)
    if head is None or body is None:
        raise StudioProjectError(f"{kind}: composition has no <head>/<body>")
    root = _ROOT_TAG_RE.search(body.group("inner"))
    if root is None:
        raise StudioProjectError(f"{kind}: no data-composition-id root in body")
    if f'data-composition-id="{kind}"' not in root.group(0):
        raise StudioProjectError(
            f"{kind}: root data-composition-id does not equal the kind")
    root_id = _ROOT_ID_RE.search(root.group(0))
    if root_id is None:
        raise StudioProjectError(f"{kind}: composition root has no id attribute")
    body_html = inline_local_body_scripts(body.group("inner").strip("\n"))
    if scope_styles:
        body_html = bind_instance_styles(body_html, root_id.group(1))
    return SourceComp(
        kind=kind,
        styles="\n".join(_STYLE_RE.findall(head.group("inner"))),
        body=body_html,
        root_el_id=root_id.group(1),
        variables=declared_variables(comp_html),
        uses_split_text="SplitText" in comp_html or "SplitText" in body_html,
        uses_motion_tokens="__motionTokens" in comp_html or "__motionTokens" in body_html,
        bind_duration=bind_duration)


def rewrite_icon_refs(text: str) -> str:
    """Mirror the comp-html route's /icons rewrite (static src AND the comps'
    runtime ``"/icons/" + file`` string concat) onto the project's assets."""
    return text.replace('"/icons/', '"assets/icons/')


def attr_json(payload: object) -> str:
    """JSON for a single-quoted HTML attribute, parseable from RAW file text.

    Studio's lint ``JSON.parse``s the attribute text as it sits in the file
    (entities are NOT decoded), so HTML-escaping with ``&quot;`` breaks it.
    Instead ``'``, ``&``, ``<`` and ``>`` — which in serialized JSON can only
    occur inside string literals — are escaped as ``\\uXXXX``, which both
    ``JSON.parse`` and the DOM attribute round-trip preserve.
    """
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")) if isinstance(payload, dict) \
        else json.dumps(payload, ensure_ascii=True, separators=(", ", ": "))
    return (text.replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("'", "\\u0027"))


def _retarget_page_selectors(styles: str, root_el_id: str) -> str:
    """Point html/body-only rules at the comp root; fail loud on the rest."""
    retargeted = _PAGE_RULE_RE.sub(
        lambda m: f"{m.group('lead')}{m.group('gap')}#{root_el_id} {{", styles)
    leftover = _PAGE_LEFTOVER_RE.search(
        re.sub(r"/\*.*?\*/", "", retargeted, flags=re.DOTALL))
    if leftover is not None:
        raise StudioProjectError(
            f"#{root_el_id}: composition CSS still targets html/body outside a "
            "retargetable rule — cannot scope it to the mounted instance")
    return retargeted


def _rewrite_root_tag(body: str, kind: str, instance_id: str) -> str:
    """Give the root tag the unique instance id (+ data-start when absent)."""
    match = _ROOT_TAG_RE.search(body)
    if match is None:
        raise StudioProjectError(f"{kind}: no data-composition-id root in body")
    tag = match.group(0).replace(
        f'data-composition-id="{kind}"',
        f'data-composition-id="{instance_id}"', 1)
    if "data-start=" not in tag:
        tag = tag.replace(
            f'data-composition-id="{instance_id}"',
            f'data-composition-id="{instance_id}" data-start="0"', 1)
    return body[:match.start()] + tag + body[match.end():]


def _rewrite_timeline_key(body: str, kind: str, instance_id: str) -> str:
    """Re-key the string-literal ``__timelines[<kind>]`` registration."""
    pattern = re.compile(
        r"__timelines\[\s*(['\"])" + re.escape(kind) + r"\1\s*\]")
    rewritten, count = pattern.subn(f'__timelines["{instance_id}"]', body)
    if count == 0:
        raise StudioProjectError(
            f"{kind}: timeline registration is not the string literal "
            f"__timelines[\"{kind}\"] — cannot rewrite it to {instance_id}")
    return rewritten


def _panel_compatible(row: dict, value: object) -> bool:
    """Whether the value can seed this declaration's panel default."""
    declared = row.get("type")
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "enum":
        return any(option.get("value") == value
                   for option in row.get("options", [])
                   if isinstance(option, dict))
    expected = _SCALAR_TYPES.get(str(declared))
    return expected is not None and isinstance(value, expected)


def seed_declarations(variables: dict[str, dict],
                      spec: dict) -> tuple[str, tuple[str, ...]]:
    """Declarations JSON with defaults pre-seeded from the entry's spec.

    Returns the serialized array plus the spec keys the properties panel
    cannot edit (non-scalar values, or keys with no declaration) — those
    still reach the instance only through ``data-variable-values``.
    """
    rows = []
    non_panel = []
    for key, row in variables.items():
        seeded = dict(row)
        if key in spec and _panel_compatible(row, spec[key]):
            seeded["default"] = spec[key]
        rows.append(seeded)
    for key, value in spec.items():
        if key not in variables or not _panel_compatible(variables[key], value):
            non_panel.append(key)
    return attr_json(rows), tuple(sorted(non_panel))


def _extra_head(source: SourceComp) -> str:
    """Standalone-shell script tags (the mounted path ignores the head)."""
    lines = []
    if source.uses_split_text:
        lines.append('    <script src="../assets/vendor/SplitText.min.js">'
                     "</script>\n")
    if source.uses_motion_tokens:
        lines.append('    <script src="../assets/vendor/motion-tokens.js">'
                     "</script>\n")
    return "".join(lines)


def standalone_vars(variables: dict[str, dict], spec: dict) -> str:
    """This instance's effective variables as inline-script JSON.

    Declared defaults overlaid with the entry's spec — exactly what the
    scoped host mount resolves from declarations + ``data-variable-values``.
    ``attr_json`` escaping also keeps ``</script`` impossible inside the
    inline script block.
    """
    merged = {key: row["default"] for key, row in variables.items()
              if "default" in row}
    merged.update(spec)
    return attr_json(merged)


def native_text_assignment(seed: str) -> str:
    """Known Studio-only binding: native copy wins only after a leaf edit.

    An unchanged seeded leaf still follows host variables. A native edit,
    including an empty string, survives a fresh mounted or standalone preview.
    The import bridge proves this exact assignment and rejects conflicting
    native/host edits; the final renderer keeps the original template binding.
    """
    return ('const el = document.getElementById("te-text");\n'
            f'        const initialText = {attr_json(seed)};\n'
            '        el.textContent = el.textContent === initialText '
            '? String(vars.text) : el.textContent;')


def _native_text_leaf(body: str, source: SourceComp, spec: dict) -> str:
    """Seed only the registered plain-text leaf; reject changed anatomy."""
    if source.kind != "text-element":
        return body
    seed = spec.get("text", source.variables["text"]["default"])
    if not isinstance(seed, str) or "\x00" in seed:
        raise StudioProjectError("text-element: native copy requires string text without NUL")
    assignment = (r'const el = document\.getElementById\("te-text"\);\s*'
                  r'el\.textContent = String\(vars\.text\);')
    body, assigned = re.subn(assignment, lambda _: native_text_assignment(seed), body)
    # A character reference survives HTML's initial CR/CRLF normalization.
    escaped = html.escape(seed).replace("\r", "&#13;")
    body, seeded = re.subn(r'(<div id="te-text"[^>]*>)</div>',
                          lambda match: match[1] + escaped + '</div>', body)
    if assigned != 1 or seeded != 1:
        raise StudioProjectError("text-element: native copy source anatomy changed")
    return body


def build_instance(source: SourceComp, plan: InstancePlan) -> InstanceBuild:
    """Build one per-instance sub-composition file from a source comp."""
    body = _rewrite_root_tag(source.body, source.kind, plan.instance_id)
    body = _rewrite_timeline_key(body, source.kind, plan.instance_id)
    body = set_root_duration(body, plan.duration)
    if source.bind_duration:
        body = bind_mounted_duration(body)
    body = rewrite_icon_refs(body)
    body = _native_text_leaf(body, source, plan.spec)
    styles = rewrite_icon_refs(
        _retarget_page_selectors(source.styles, source.root_el_id))
    declarations, non_panel = seed_declarations(source.variables, plan.spec)
    page = _INSTANCE_SHELL.format(
        declarations=declarations,
        instance_id=plan.instance_id,
        extra_head=_extra_head(source),
        standalone_vars=standalone_vars(source.variables, plan.spec),
        styles=styles,
        body=body)
    return InstanceBuild(plan.instance_id, page, non_panel)
