#!/usr/bin/env python3
"""deep_semantics — P6: the OPT-IN agent micro-layer (--semantics).

Everything measurable stayed deterministic (P1-P5); the ONLY thing left for an
agent is naming what a graphic IS — its kind, styling vocabulary and layout.
This harness turns each detected graphic event into ONE bounded, schema-forced
micro-task: three frames (entrance / settled / exit) are extracted next to the
study, and a single ``claude -p`` call per event must answer as strict JSON:

    {"kindGuess": str, "stylingTokens": [str, ...], "layout": str}

House rules: skills-only (subscription admission, never an implicit paid API), per-event,
capped at ``semantics_max_events``, and SKIPPABLE — the core pipeline runs
with zero AI; a malformed reply is recorded as that event's error, loudly,
without sinking the deterministic study. ``spawn`` is injectable so tests
exercise the whole harness without any agent.

The legacy automatic CLI invocation is currently blocked pending shared
subscription admission. Request a Codex subscription-agent review of the local
evidence explicitly; this module never switches providers automatically and
does not establish account-level overage policy.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402
from study.deep_frames import VideoInfo, Window, decode_window  # noqa: E402

SCHEMA_KEYS = {"kindGuess": str, "stylingTokens": list, "layout": str}
SEMANTIC_TYPES = ("graphic-in", "panel-in")
DEFAULT_CLAUDE_MODEL = "sonnet"
CLAUDE_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\[\]\-]{0,159}$")

PROMPT = """You are naming ONE on-screen graphic from a reference video.
Look at the three attached frames (entrance, settled, exit) at:
{frames}

The deterministic extractor already measured: type={etype}, bbox={bbox},
coverage={coverage}, text="{text}".

Reply with STRICT JSON only — no prose, no markdown fences — matching:
{{"kindGuess": "<stat-card|lower-third|list|quote|logo|chart|other>",
  "stylingTokens": ["<up to 6 short style words: e.g. serif, neon, glass>"],
  "layout": "<one line: where it sits and how it is arranged>"}}"""


def event_frames(video: str, info: VideoInfo, event: dict,
                 out_dir: str) -> list[str]:
    """Save the event's entrance/settled/exit frames as JPGs; return paths."""
    import cv2
    frames_dir = os.path.join(out_dir, "events")
    os.makedirs(frames_dir, exist_ok=True)
    t0 = float(event["t"])
    hold = max(event.get("durationFrames", 1) / 30.0, 0.5)
    times = (t0, min(info.duration - 0.05, t0 + hold),
             min(info.duration - 0.05, t0 + 2.0 * hold))
    paths = []
    for tag, t in zip(("in", "hold", "out"), times):
        win = Window(t0=max(0.0, t), t1=max(0.0, t) + 0.5, fps=4.0, width=None)
        frames = decode_window(video, win, info, "bgr24")
        if not frames:
            raise RuntimeError(f"semantics frame extract empty at t={t:.2f}s")
        path = os.path.join(frames_dir, f"{event['id']}_{tag}.jpg")
        cv2.imwrite(path, frames[0])
        paths.append(path)
    return paths


def build_prompt(event: dict, frames: list[str]) -> str:
    """The schema-forced micro-prompt for one event."""
    return PROMPT.format(frames="\n".join(frames), etype=event["type"],
                         bbox=event.get("bbox"),
                         coverage=event.get("coverage"),
                         text=event.get("_text") or "")


def claude_model() -> str:
    """Return the explicit subscription model; never inherit a CLI default."""
    model = os.environ.get("SNIPER_CLAUDE_MODEL", "").strip()
    model = model or DEFAULT_CLAUDE_MODEL
    if not CLAUDE_MODEL_RE.fullmatch(model):
        raise RuntimeError("SNIPER_CLAUDE_MODEL is not a safe Claude model identifier")
    return model


def _default_spawn(prompt: str) -> str:
    """Block the unqualified legacy invocation before any provider process."""
    raise RuntimeError(
        "Subscription admission not qualified for automatic study semantics; "
        "request a Codex subscription-agent review of local evidence explicitly. "
        "No semantic analysis ran and no provider fallback was attempted.")


def parse_reply(raw: str) -> dict:
    """Validate the strict-JSON reply against the micro-schema (fail loudly)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in reply: {raw[:120]!r}")
    obj = json.loads(raw[start:end + 1])
    for key, kind in SCHEMA_KEYS.items():
        if not isinstance(obj.get(key), kind):
            raise ValueError(f"reply missing/mistyped {key!r}: {obj.get(key)!r}")
    return {k: obj[k] for k in SCHEMA_KEYS}


def run_semantics(video: str, info: VideoInfo, events: list[dict],
                  out_dir: str, spawn=None) -> dict:
    """The whole opt-in pass: per-event frames → micro-call → validated rows."""
    if spawn is None:
        _default_spawn("")
    targets = [e for e in events if e["type"] in SEMANTIC_TYPES]
    targets = targets[:DEEP["semantics_max_events"]]
    rows = []
    for ev in targets:
        row = {"eventId": ev["id"], "t": ev["t"], "type": ev["type"]}
        try:
            frames = event_frames(video, info, ev, out_dir)
            row.update(parse_reply(spawn(build_prompt(ev, frames))))
            row["frames"] = frames
        except (RuntimeError, ValueError, json.JSONDecodeError,
                subprocess.TimeoutExpired) as exc:
            row["error"] = str(exc)
        rows.append(row)
    return {"ran": True, "eventsConsidered": len(targets), "events": rows}
