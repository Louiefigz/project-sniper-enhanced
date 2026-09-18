"""Negative fail-fast health guard for the exact approved HyperFrames CLI.

Logs are not visual approval or authentication. This prevents known fatal page,
required-resource, and missing-timeline symptoms from becoming encoded success.
Positive timeline/pixel checks remain separate qualification evidence.
"""
from __future__ import annotations

import codecs
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

MAX_LOG_BYTES = 1024 * 1024
TIMELINE_WAIT_SECONDS = 5.0
CLI_PATH = "/opt/sniper-motion/node_modules/hyperframes/dist/cli.js"
CLI_SHA256 = "95be44729e244283cb685833a20b94e00c96aaafba7848b9182db01771477c78"
_FATAL = re.compile(r"\[(?:Browser:(?:PAGEERROR|ERROR|REQUESTFAILED|HTTP[45][0-9]{2})|FrameCapture:ERROR)\]"
                    r"|\[FileServer\] [45][0-9]{2} |Sub-composition timelines not registered after"
                    r"|pollSubCompositionTimelines complete \((?:timeout|script_failure)\)"
                    r"|\[non-blocking\] Failed to load resource")
_READY = re.compile(r"\[initSession:(?:screenshot|beginframe)\] pollHfReady complete")
# 0.8.31 reports a completion even when its wait timed out or lost a script.
_TIMELINE = re.compile(r"\[initSession:(?:screenshot|beginframe)\] pollSubCompositionTimelines complete \(ready\)")


def require_supported_cli(approval: dict) -> None:
    """Do not silently reuse version-specific health markers for another CLI."""
    closure = approval.get("probedClosure", {})
    if closure.get("hyperframesVersion") != "0.8.31" or closure.get("sha256", {}).get(CLI_PATH) != CLI_SHA256:
        raise RuntimeError("render log health guard requires the audited HyperFrames0.8.31 CLI identity")


def read_render_log(runtime: Any, config_dir: str, name: str) -> bytes:
    """Read only one fixed container log with an explicit byte/time ceiling."""
    from headless.container_policy import command, docker_env
    result = subprocess.run(command(runtime, "container", "exec", name, "/usr/bin/head", "-c",
                                    str(MAX_LOG_BYTES + 1), "/output/render.log"),
                            stdin=subprocess.DEVNULL, capture_output=True, env=docker_env(config_dir), timeout=10)
    if result.returncode != 0:
        raise RuntimeError("required renderer health log could not be read")
    if len(result.stdout) > MAX_LOG_BYTES:
        raise RuntimeError("renderer health log exceeded its byte budget")
    return result.stdout


@dataclass
class RenderLogGuard:
    """Require append-only bounded diagnostics; never classify pixels by logs."""

    previous: bytes = b""
    text: str = ""
    pending_since: float | None = None
    decoder: Any = field(default_factory=lambda: codecs.getincrementaldecoder("utf-8")("strict"))

    def observe(self, data: bytes, now: float, finished: bool = False) -> None:
        """Fail on known fatal symptoms or a short missing-timeline deadline."""
        if len(data) > MAX_LOG_BYTES or not data.startswith(self.previous):
            raise RuntimeError("renderer health log overflowed, changed, or was truncated")
        self.text += self.decoder.decode(data[len(self.previous):], final=finished)
        self.previous = data
        failure = _FATAL.search(self.text)
        if failure:
            snippet = self.text[failure.start():].splitlines()[0][:240]
            raise RuntimeError(f"renderer runtime health failed: {snippet}")
        ready, timelines = len(_READY.findall(self.text)), len(_TIMELINE.findall(self.text))
        if ready > timelines:
            self.pending_since = now if self.pending_since is None else self.pending_since
        else:
            self.pending_since = None
        if self.pending_since is not None and now - self.pending_since >= TIMELINE_WAIT_SECONDS:
            raise RuntimeError("renderer timeline registration did not complete within5 seconds; output rejected")
        if finished and (ready == 0 or ready != timelines):
            raise RuntimeError("renderer ended without complete pinned runtime readiness diagnostics")
