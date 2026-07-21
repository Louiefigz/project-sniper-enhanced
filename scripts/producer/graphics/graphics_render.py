"""HyperFrames render, proof, and content-hash cache for one graphic entry."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from fingerprints import json_canon
from graphics.asset_proof import AssetProofRequest, prove_rendered_asset
from graphics.composition_transform import set_root_duration
from graphics.pip_hole import entry_has_hole
from graphics.render_cache import CacheRequest, materialize
from headless.container_io import CompositionInput, SealedInput, create_snapshot
from headless.runtime_receipt import bind_runtime_receipt
from headless.container_renderer import (
    RenderRequest as ContainerRenderRequest,
    cache_identity as container_cache_identity,
    render_to as render_in_container,
)
from graphics.template_contract import (
    composition_dimensions,
    resolved_assets,
    validate_entry,
)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.environ.get(
    "SNIPER_PIPELINE_ROOT",
    os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..")))
RUNTIME_ROOT = os.environ.get("SNIPER_RUNTIME_REPO_ROOT", PIPELINE_ROOT)
MOTION_DIR = os.path.join(PIPELINE_ROOT, "templates", "motion")
COMPOSITIONS_DIR = os.path.join(MOTION_DIR, "compositions")
TOKENS_CSS = os.path.join(MOTION_DIR, "tokens.css")
MOTION_TOKENS_JS = os.path.join(MOTION_DIR, "motion-tokens.js")
GSAP_CORE = os.path.join(MOTION_DIR, "vendor", "gsap", "gsap.min.js")
NODE_USER_PRELOAD = os.path.join(os.path.dirname(SCRIPT_DIR), "headless",
                                 "node_isolated_user.cjs")
DEFAULT_CACHE_DIR = os.path.join(MOTION_DIR, "renders", "cache")
_LOCAL_GSAP_SRC = "/vendor/gsap/gsap.min.js"
_PINNED_TOOL_ENV = {
    "node": "SNIPER_NODE_PATH",
    "browser": "HYPERFRAMES_BROWSER_PATH",
    "ffmpeg": "HYPERFRAMES_FFMPEG_PATH",
    "ffprobe": "HYPERFRAMES_FFPROBE_PATH",
}


def hyperframes_bin(runtime_root: str) -> str:
    """Project-local CLI module from executable runtime, not pipeline snapshot."""
    return os.path.join(runtime_root, "templates", "motion", "node_modules",
                        "hyperframes", "dist", "cli.js")


HYPERFRAMES_BIN = hyperframes_bin(RUNTIME_ROOT)

def _pinned_tools() -> dict[str, str]:
    """Resolve required executables without mutable PATH-based discovery."""
    resolved = {}
    for name, env_key in _PINNED_TOOL_ENV.items():
        raw = os.environ.get(env_key, "").strip()
        if not raw or not os.path.isabs(raw):
            raise RuntimeError(f"{env_key} must be an absolute executable path")
        path = os.path.realpath(raw)
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise RuntimeError(f"{env_key} is not an executable file: {raw}")
        resolved[name] = path
    return resolved


def _render_environment(runtime_dir: str, tools: dict[str, str]) -> dict[str, str]:
    """Build a secret-free environment rooted in attempt-owned directories."""
    dirs = {name: os.path.join(runtime_dir, name)
            for name in ("user", "tmp", "cache", "config", "data", "state",
                         "fonts", "extract", "heygen")}
    for path in dirs.values():
        os.mkdir(path, mode=0o700)
    env: dict[str, str] = {}
    path_dirs = [os.path.dirname(tools[name]) for name in sorted(tools)]
    env.update({
        "PATH": os.pathsep.join(dict.fromkeys(path_dirs + ["/usr/bin", "/bin"])),
        "TMPDIR": dirs["tmp"], "TMP": dirs["tmp"], "TEMP": dirs["tmp"],
        "XDG_CACHE_HOME": dirs["cache"],
        "XDG_CONFIG_HOME": dirs["config"], "XDG_DATA_HOME": dirs["data"],
        "XDG_STATE_HOME": dirs["state"], "HEYGEN_CONFIG_DIR": dirs["heygen"],
        "PUPPETEER_CACHE_DIR": dirs["cache"],
        "SNIPER_ISOLATED_USER_DIR": dirs["user"],
        "NODE_OPTIONS": f"--require={NODE_USER_PRELOAD}",
        "HYPERFRAMES_BROWSER_PATH": tools["browser"],
        "PRODUCER_HEADLESS_SHELL_PATH": tools["browser"],
        "HYPERFRAMES_FFMPEG_PATH": tools["ffmpeg"],
        "HYPERFRAMES_FFPROBE_PATH": tools["ffprobe"],
        "HYPERFRAMES_FONT_CACHE_DIR": dirs["fonts"],
        "HYPERFRAMES_EXTRACT_CACHE_DIR": dirs["extract"],
        "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_AUTO_INSTALL": "1",
        "HYPERFRAMES_NO_TELEMETRY": "1",
        "HYPERFRAMES_NO_UPDATE_CHECK": "1", "HYPERFRAMES_SKIP_SKILLS": "1",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "LC_CTYPE": "C.UTF-8",
        "TZ": "UTC", "PRODUCER_LOW_MEMORY_MODE": "false", "NO_COLOR": "1",
        "NO_PROXY": "127.0.0.1,localhost,::1",
    })
    return env

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
    """Extend render media enough to cover its rounded timeline frame span."""
    if fps <= 0:
        raise ValueError("timeline fps must be positive")
    start, end = float(entry["outStart"]), float(entry["outEnd"])
    frame_span = round(end * fps) - round(start * fps)
    required = frame_span / fps
    if required <= end - start:
        return entry
    padded = dict(entry)
    padded["outEnd"] = start + required
    return padded


def comp_path(kind: str) -> str:
    """Absolute path to the ``kind`` composition; raise if it is not a template."""
    path = os.path.join(COMPOSITIONS_DIR, f"{kind}.html")
    if not os.path.isfile(path):
        raise ValueError(f"unknown graphic kind '{kind}': no compositions/{kind}.html")
    return path


_set_root_duration = set_root_duration


def content_hash(kind: str, spec: dict, duration: float, comp_html: str) -> str:
    """Hash canonical intent plus every resolved template/runtime input."""
    h = hashlib.sha1()
    h.update(kind.encode("utf-8"))
    h.update(json.dumps(json_canon(spec), sort_keys=True,
                        ensure_ascii=True).encode("utf-8"))
    h.update(f"{duration:.4f}".encode("utf-8"))
    h.update(hashlib.sha1(comp_html.encode("utf-8")).digest())
    shared_files = [TOKENS_CSS, MOTION_TOKENS_JS]
    if _LOCAL_GSAP_SRC in comp_html:
        shared_files.append(GSAP_CORE)
    for shared in shared_files:
        with open(shared, "rb") as f:
            h.update(hashlib.sha1(f.read()).digest())
    for asset in resolved_assets({"kind": kind, "spec": spec}, comp_html):
        with open(asset["path"], "rb") as handle:
            h.update(asset["field"].encode("utf-8"))
            h.update(hashlib.sha1(handle.read()).digest())
    if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
        h.update(container_cache_identity(PIPELINE_ROOT))
    return h.hexdigest()


def _sealed_hash(kind: str, snapshot: SealedInput) -> str:
    digest = hashlib.sha1()
    digest.update(b"sealed-render-input-v1")
    digest.update(kind.encode("utf-8"))
    digest.update(snapshot.sha256.encode("ascii"))
    digest.update(container_cache_identity(PIPELINE_ROOT))
    return digest.hexdigest()


def _render_to(temp_comp_rel: str, fmt: str, spec: dict, out_path: str) -> None:
    """Invoke pinned HyperFrames with private ambient state."""
    cli_path = os.path.realpath(HYPERFRAMES_BIN)
    if not os.path.isfile(cli_path):
        raise RuntimeError("pinned HyperFrames install is missing; run npm ci in "
                           f"{MOTION_DIR}")
    if not os.path.isfile(NODE_USER_PRELOAD):
        raise RuntimeError(f"Node isolation preload is missing: {NODE_USER_PRELOAD}")
    tools = _pinned_tools()
    out_path = os.path.abspath(out_path)
    cmd = [tools["node"], cli_path, "render", MOTION_DIR,
           "-c", temp_comp_rel, "--format", fmt,
           "--variables", json.dumps(spec), "-o", out_path, "--fps", "30",
           "--quality", "high", "--workers", "1", "--no-browser-gpu",
           "--strict", "--strict-variables", "--json"]
    out_dir = os.path.dirname(out_path)
    with tempfile.TemporaryDirectory(prefix=".hyperframes-", dir=out_dir) as scratch:
        render_env = _render_environment(scratch, tools)
        proc = subprocess.run(cmd, cwd=scratch, env=render_env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-10:])
        raise RuntimeError(f"hyperframes render failed for {temp_comp_rel}:\n{tail}")
    if not os.path.exists(out_path):
        raise RuntimeError(f"hyperframes reported success but {out_path} is missing")


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


def _render_candidate(work: _RenderWork, output: str) -> None:
    if work.snapshot is not None:
        render_in_container(ContainerRenderRequest(
            work.temp_rel, work.fmt, output, work.snapshot,
            os.environ.get("SNIPER_RENDER_CONTAINER_NAME", "")))
        return
    try:
        with open(work.temp_abs, "w", encoding="utf-8") as handle:
            handle.write(_set_root_duration(work.comp_html, work.duration))
        _render_to(work.temp_rel, work.fmt, work.spec, output)
    finally:
        if os.path.exists(work.temp_abs):
            os.remove(work.temp_abs)


def _prove_candidate(work: _RenderWork, path: str) -> dict:
    proof = prove_rendered_asset(AssetProofRequest(
        path, work.entry, work.fmt, work.dimensions, work.duration, work.key,
        comp_html=work.comp_html, require_terminal_clear=work.fmt == "mov",
        sealed_asset_inputs=(work.snapshot.asset_bindings
                             if work.snapshot is not None else None)))
    return bind_runtime_receipt(path, proof) if work.snapshot is not None else proof


def _materialize_work(work: _RenderWork, cache_dir: str, ext: str) -> dict:
    out_path, cached, proof = materialize(
        CacheRequest(cache_dir, work.key, ext),
        lambda path: _render_candidate(work, path),
        lambda path: _prove_candidate(work, path))
    return {"path": out_path, "cached": cached, "key": work.key,
            "kind": work.entry["kind"], "fmt": work.fmt, "proof": proof}
def render_entry(entry: dict, cache_dir: str | None = None) -> dict:
    """Render or reuse one proved graphics-track asset."""
    kind = entry["kind"]
    spec = entry.get("spec") or {}
    anchor = entry.get("anchor", "free-band")
    duration = float(entry["outEnd"]) - float(entry["outStart"])
    if duration <= 0:
        raise ValueError(f"{kind}: non-positive window {entry['outStart']}->{entry['outEnd']}")
    fmt, ext = format_for(kind, anchor, spec)
    with open(comp_path(kind), encoding="utf-8") as f:
        comp_html = f.read()
    validate_entry(entry, comp_html)
    dimensions = composition_dimensions(comp_html)
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
        with tempfile.TemporaryDirectory(prefix=".sealed-input-",
                                         dir=cache_dir) as seal_dir:
            relative = os.path.join("compositions", f"{kind}.html")
            snapshot = create_snapshot(
                PIPELINE_ROOT, CompositionInput(relative, comp_html,
                                                duration=duration),
                spec, seal_dir)
            key = _sealed_hash(kind, snapshot)
            work = _RenderWork(entry, fmt, dimensions, duration, key, relative,
                               "", comp_html, spec, snapshot)
            return _materialize_work(work, cache_dir, ext)
    key = content_hash(kind, spec, duration, comp_html)
    temp_rel = os.path.join("compositions", f"_gs-{key}.html")
    work = _RenderWork(entry, fmt, dimensions, duration, key, temp_rel,
                       os.path.join(MOTION_DIR, temp_rel), comp_html, spec, None)
    return _materialize_work(work, cache_dir, ext)
