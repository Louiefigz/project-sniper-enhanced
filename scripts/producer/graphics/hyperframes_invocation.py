"""Secret-free invocation of the pinned HyperFrames runtime."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass

from graphics.render_rate import normalize_render_rate
from graphics.render_tools import resolve_tools


@dataclass(frozen=True)
class RenderInvocation:
    """One explicit HyperFrames invocation against a closed runtime root."""

    root: str
    composition: str
    fmt: str
    variables: dict
    output: str
    fps: object = 30


def _render_environment(runtime_dir: str, tools: dict[str, str],
                        preload: str) -> dict[str, str]:
    """Build a secret-free environment rooted in attempt-owned directories."""
    names = ("user", "tmp", "cache", "config", "data", "state", "fonts",
             "extract", "heygen")
    dirs = {name: os.path.join(runtime_dir, name) for name in names}
    for path in dirs.values():
        os.mkdir(path, mode=0o700)
    path_dirs = [os.path.dirname(tools[name]) for name in sorted(tools)]
    return {
        "PATH": os.pathsep.join(dict.fromkeys(path_dirs + ["/usr/bin", "/bin"])),
        "TMPDIR": dirs["tmp"], "TMP": dirs["tmp"], "TEMP": dirs["tmp"],
        "XDG_CACHE_HOME": dirs["cache"], "XDG_CONFIG_HOME": dirs["config"],
        "XDG_DATA_HOME": dirs["data"], "XDG_STATE_HOME": dirs["state"],
        "HEYGEN_CONFIG_DIR": dirs["heygen"],
        "PUPPETEER_CACHE_DIR": dirs["cache"],
        "SNIPER_ISOLATED_USER_DIR": dirs["user"],
        "NODE_OPTIONS": f"--require={preload}",
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
    }


def _command(request: RenderInvocation, cli: str,
             tools: dict[str, str]) -> list[str]:
    rate = normalize_render_rate(request.fps)
    return [
        tools["node"], cli, "render", request.root,
        "-c", request.composition, "--format", request.fmt,
        "--variables", json.dumps(request.variables), "-o", request.output,
        "--fps", rate.token, "--quality", "high",
        "--workers", "1", "--no-browser-gpu", "--strict",
        "--strict-variables", "--json",
    ]


def render_composition(request: RenderInvocation, cli_path: str,
                       preload_path: str) -> None:
    """Invoke HyperFrames with no ambient credentials or render-time network."""
    normalize_render_rate(request.fps)
    cli = os.path.realpath(cli_path)
    if not os.path.isfile(cli):
        raise RuntimeError("pinned HyperFrames install is missing")
    if not os.path.isfile(preload_path):
        raise RuntimeError(f"Node isolation preload is missing: {preload_path}")
    tools = resolve_tools()
    output = os.path.abspath(request.output)
    normalized = RenderInvocation(
        request.root, request.composition, request.fmt, request.variables,
        output, request.fps)
    command = _command(normalized, cli, tools)
    with tempfile.TemporaryDirectory(
            prefix=".hyperframes-", dir=os.path.dirname(output)) as scratch:
        environment = _render_environment(scratch, tools, preload_path)
        proc = subprocess.run(
            command, cwd=scratch, env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True)
    if proc.returncode != 0:
        combined = "\n".join(
            part for part in (proc.stderr, proc.stdout) if part)
        tail = "\n".join(combined.strip().splitlines()[-80:])
        raise RuntimeError(
            f"hyperframes render failed for {request.composition}:\n{tail}")
    if not os.path.exists(output):
        raise RuntimeError(f"hyperframes reported success but {output} is missing")
