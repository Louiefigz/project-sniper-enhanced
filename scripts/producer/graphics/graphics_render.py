"""HyperFrames render, proof, and content-hash cache for one graphic entry."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess  # compatibility patch surface shared with invocation module
import sys
import tempfile
from dataclasses import dataclass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from graphics.visual_source_policy import require_integrated
from fingerprints import json_canon
from graphics.asset_proof import AssetProofRequest, prove_rendered_asset
from graphics.comp_capabilities import measured_fade_class
from graphics.composition_transform import set_root_duration
from graphics.frame_quantization import (
    hyperframes_duration,
    placement_frame_span,
    quantized_window_end,
)
from graphics.hyperframes_invocation import RenderInvocation, render_composition
from graphics.pip_hole import entry_has_hole
from graphics.render_cache import CacheRequest, materialize
from graphics.render_rate import normalize_render_rate
from graphics.render_tools import _PINNED_TOOL_ENV, live_tools_identity
from headless.container_io import CompositionInput, SealedInput, create_snapshot
from headless.source_closure import discover_root_sources
from headless.runtime_receipt import bind_runtime_receipt
from headless.container_renderer import (
    RenderRequest as ContainerRenderRequest,
    cache_identity as container_cache_identity,
    render_to as render_in_container,
)
from graphics.template_contract import (
    composition_dimensions,
    declared_variables,
    resolved_assets,
    validate_entry,
)
from graphics.template_visual_contract import module_land_variables
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.environ.get(
    "SNIPER_PIPELINE_ROOT", os.path.abspath(
        os.path.join(SCRIPT_DIR, "..", "..", "..")))
RUNTIME_ROOT = os.environ.get("SNIPER_RUNTIME_REPO_ROOT", PIPELINE_ROOT)
MOTION_DIR = os.path.join(PIPELINE_ROOT, "templates", "motion")
COMPOSITIONS_DIR = os.path.join(MOTION_DIR, "compositions")
TOKENS_CSS = os.path.join(MOTION_DIR, "tokens.css")
MOTION_TOKENS_JS = os.path.join(MOTION_DIR, "motion-tokens.js")
GSAP_CORE = os.path.join(MOTION_DIR, "vendor", "gsap", "gsap.min.js")
NODE_USER_PRELOAD = os.path.join(
    os.path.dirname(SCRIPT_DIR), "headless", "node_isolated_user.cjs")
DEFAULT_CACHE_DIR = os.path.join(MOTION_DIR, "renders", "cache")
_LOCAL_GSAP_SRC = "/vendor/gsap/gsap.min.js"
_CONTENT_ARGS = ("kind", "spec", "duration", "comp_html", "fps")
_RENDER_ARGS = ("temp_comp_rel", "fmt", "spec", "out_path", "fps")


def hyperframes_bin(runtime_root: str) -> str:
    """Project-local CLI module from executable runtime, not pipeline snapshot."""
    return os.path.join(runtime_root, "templates", "motion", "node_modules",
                        "hyperframes", "dist", "cli.js")


HYPERFRAMES_BIN = hyperframes_bin(RUNTIME_ROOT)

_ALPHA = ("mov", "mov")
_FORMAT_BY_ANCHOR = {
    "own-screen": ("mp4", "mp4"),
    "free-band": _ALPHA,
    "focus-shift": _ALPHA,
    "headroom": _ALPHA,
    "chest": _ALPHA,
    "beside-face": _ALPHA,
}
def format_for(kind: str, anchor: str, spec: dict | None = None) -> tuple[str, str]:
    """Choose format by anchor, preserving alpha around active face holes."""
    if anchor not in _FORMAT_BY_ANCHOR:
        raise ValueError(f"{kind}: unknown anchor '{anchor}' (free-band|own-screen)")
    if entry_has_hole({"kind": kind, "spec": spec}):
        return _ALPHA
    return _FORMAT_BY_ANCHOR[anchor]


def timeline_padded_entry(entry: dict, fps: float) -> dict:
    """Quantize render media to its exact rounded timeline frame span.

    The compatibility name remains because Palmier callers already import it;
    unlike the former implementation this can shorten or extend by <1 frame.
    """
    start, end = float(entry["outStart"]), float(entry["outEnd"])
    frame_span = placement_frame_span(start, end, fps)
    quantized_end = quantized_window_end(start, frame_span, fps)
    if quantized_end == end:
        return entry
    quantized = dict(entry)
    quantized["outEnd"] = quantized_end
    return quantized


def comp_path(kind: str) -> str:
    """Absolute path to the ``kind`` composition; raise if it is not a template."""
    require_integrated(kind)
    path = os.path.join(COMPOSITIONS_DIR, f"{kind}.html")
    if not os.path.isfile(path):
        raise ValueError(f"unknown graphic kind '{kind}': no compositions/{kind}.html")
    return path


def _bind_compat_call(
    arguments: tuple[object, ...],
    keywords: dict[str, object],
    names: tuple[str, ...],
    defaults: dict[str, object],
) -> dict[str, object]:
    """Bind the former explicit signature behind a low-arity adapter."""
    if len(arguments) > len(names):
        raise TypeError("too many positional arguments")
    unexpected = set(keywords) - set(names)
    if unexpected:
        name = sorted(unexpected)[0]
        raise TypeError(f"unexpected keyword argument {name!r}")
    bound = dict(zip(names, arguments))
    for name, value in keywords.items():
        if name in bound:
            raise TypeError(f"{name} received multiple values")
        bound[name] = value
    missing = [name for name in names
               if name not in bound and name not in defaults]
    if missing:
        raise TypeError(f"missing required argument: {missing[0]!r}")
    return {name: bound.get(name, defaults.get(name)) for name in names}


def content_hash(*arguments: object, **keywords: object) -> str:
    """Hash canonical intent plus every resolved template/runtime input."""
    call = _bind_compat_call(
        arguments, keywords, _CONTENT_ARGS, {"fps": 30})
    kind, spec = call["kind"], call["spec"]
    duration, comp_html, fps = (
        call["duration"], call["comp_html"], call["fps"])
    rate = normalize_render_rate(fps)
    h = hashlib.sha1()
    h.update(kind.encode("utf-8"))  # type: ignore[union-attr]
    h.update(json.dumps(json_canon(spec), sort_keys=True,
                        ensure_ascii=True).encode("utf-8"))
    h.update(f"{duration:.4f}".encode("utf-8"))  # type: ignore[str-format]
    h.update(f"fps={rate.token}".encode("ascii"))
    h.update(hashlib.sha1(comp_html.encode("utf-8")).digest())  # type: ignore[union-attr]
    shared_files = [TOKENS_CSS, MOTION_TOKENS_JS]
    if _LOCAL_GSAP_SRC in comp_html:
        shared_files.append(GSAP_CORE)
    for shared in shared_files:
        with open(shared, "rb") as f:
            h.update(hashlib.sha1(f.read()).digest())
    closure = discover_root_sources(comp_html, MOTION_DIR)
    for relative, data in sorted(closure.items()):
        h.update(relative.encode("utf-8"))
        h.update(hashlib.sha1(data).digest())
    for asset in resolved_assets(  # type: ignore[arg-type]
            {"kind": kind, "spec": spec}, comp_html):
        with open(asset["path"], "rb") as handle:
            h.update(asset["field"].encode("utf-8"))
            h.update(hashlib.sha1(handle.read()).digest())
    if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
        h.update(container_cache_identity(PIPELINE_ROOT))
    else:
        h.update(live_tools_identity())
    return h.hexdigest()


def _sealed_hash(kind: str, snapshot: SealedInput, fps: object) -> str:
    rate = normalize_render_rate(fps)
    digest = hashlib.sha1()
    digest.update(b"sealed-render-input-v1")
    digest.update(kind.encode("utf-8"))
    digest.update(snapshot.sha256.encode("ascii"))
    digest.update(f"fps={rate.token}".encode("ascii"))
    digest.update(container_cache_identity(PIPELINE_ROOT))
    return digest.hexdigest()


def _render_to(*arguments: object, **keywords: object) -> None:
    """Invoke resolved HyperFrames tools with private ambient state.

    Live default discovers absolute tool paths (explicit env pins win per
    tool); sealed mode requires every pin — see ``graphics.render_tools``.
    """
    call = _bind_compat_call(arguments, keywords, _RENDER_ARGS, {"fps": 30})
    render_composition(
        RenderInvocation(
            MOTION_DIR, call["temp_comp_rel"], call["fmt"], call["spec"],
            call["out_path"], call["fps"]),  # type: ignore[arg-type]
        HYPERFRAMES_BIN, NODE_USER_PRELOAD)


@dataclass(frozen=True)
class _RenderWork:
    entry: dict
    fmt: str
    dimensions: tuple[int, int]
    duration: float
    key: str
    temp_rel: str
    temp_abs: str
    comp_html: str
    spec: dict
    snapshot: SealedInput | None
    capability_probe: bool
    fps: object


def _render_candidate(work: _RenderWork, output: str) -> None:
    if work.snapshot is not None:
        render_in_container(ContainerRenderRequest(
            work.temp_rel, work.fmt, output, work.snapshot,
            os.environ.get("SNIPER_RENDER_CONTAINER_NAME", ""),
            work.fps))
        return
    try:
        with open(work.temp_abs, "w", encoding="utf-8") as handle:
            handle.write(set_root_duration(work.comp_html, work.duration))
        rate_arg = () if normalize_render_rate(work.fps).token == "30" else (work.fps,)
        _render_to(work.temp_rel, work.fmt, work.spec, output, *rate_arg)
    finally:
        if os.path.exists(work.temp_abs):
            os.remove(work.temp_abs)


def _terminal_clear_required(work: _RenderWork) -> bool:
    """Use fresh measured fade physics; probes measure without pre-judging."""
    if work.fmt != "mov" or work.capability_probe:
        return False
    return measured_fade_class(work.entry["kind"]) not in {
        "hold-to-cut", "partial-fade",
    }


def _prove_candidate(work: _RenderWork, path: str) -> dict:
    proof = prove_rendered_asset(AssetProofRequest(
        path, work.entry, work.fmt, work.dimensions, work.duration, work.key,
        expected_fps=normalize_render_rate(work.fps).numeric,
        comp_html=work.comp_html,
        require_terminal_clear=_terminal_clear_required(work),
        sealed_asset_inputs=(work.snapshot.asset_bindings
                             if work.snapshot is not None else None)))
    return bind_runtime_receipt(path, proof) if work.snapshot is not None else proof


def _materialize_work(work: _RenderWork, cache_dir: str, ext: str) -> dict:
    out_path, cached, proof = materialize(
        CacheRequest(cache_dir, work.key, ext),
        lambda path: _render_candidate(work, path),
        lambda path: _prove_candidate(work, path))
    return {"path": out_path, "cached": cached, "key": work.key,
            "kind": work.entry["kind"], "fmt": work.fmt,
            "fps": normalize_render_rate(work.fps).token,
            "proof": proof}
def _render_entry(entry: dict, cache_dir: str | None,
                  capability_probe: bool, fps: object) -> dict:
    """Render through the production path with an explicit proof policy."""
    kind = entry["kind"]
    spec = entry.get("spec") or {}
    anchor = entry.get("anchor", "free-band")
    planned_duration = float(entry["outEnd"]) - float(entry["outStart"])
    if planned_duration <= 0:
        raise ValueError(f"{kind}: non-positive window {entry['outStart']}->{entry['outEnd']}")
    rate = normalize_render_rate(fps)
    quantized = timeline_padded_entry(entry, rate.numeric)
    frame_count = placement_frame_span(
        float(entry["outStart"]), float(entry["outEnd"]), rate.numeric)
    duration = hyperframes_duration(frame_count, rate.numeric)
    fmt, ext = format_for(kind, anchor, spec)
    with open(comp_path(kind), encoding="utf-8") as f:
        comp_html = f.read()
    validate_entry(entry, comp_html)
    if quantized is not entry:
        validate_entry(quantized, comp_html)
    variables = module_land_variables(spec, declared_variables(comp_html))
    dimensions = composition_dimensions(comp_html)
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
        with tempfile.TemporaryDirectory(prefix=".sealed-input-",
                                         dir=cache_dir) as seal_dir:
            relative = os.path.join("compositions", f"{kind}.html")
            snapshot = create_snapshot(
                PIPELINE_ROOT, CompositionInput(
                    relative, comp_html, render_intent={
                        "fps": rate.token}, duration=duration),
                variables, seal_dir)
            key = _sealed_hash(kind, snapshot, rate.token)
            work = _RenderWork(entry, fmt, dimensions, duration, key, relative,
                               "", comp_html, variables, snapshot, capability_probe,
                               rate.token)
            return _materialize_work(work, cache_dir, ext)
    key = content_hash(kind, spec, duration, comp_html, rate.token)
    temp_rel = os.path.join("compositions", f"_gs-{key}.html")
    work = _RenderWork(entry, fmt, dimensions, duration, key, temp_rel,
                       os.path.join(MOTION_DIR, temp_rel), comp_html, variables, None,
                       capability_probe, rate.token)
    return _materialize_work(work, cache_dir, ext)


def render_entry(entry: dict, cache_dir: str | None = None) -> dict:
    """Render or reuse one production-proved graphics-track asset."""
    return _render_entry(entry, cache_dir, False, 30)

def render_entry_at_rate(entry: dict, cache_dir: str | None, fps: object) -> dict:
    """Render production graphics at one explicitly normalized target rate."""
    return _render_entry(entry, cache_dir, False, fps)

def render_entry_for_capability_probe(entry: dict, cache_dir: str | None = None, fps: object = 30) -> dict:
    """Render one asset while measuring, rather than assuming, fade physics."""
    return _render_entry(entry, cache_dir, True, fps)
