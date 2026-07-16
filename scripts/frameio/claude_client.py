"""Claude vision client — one frame in, structured list of text errors out.

The model is a config constant (swap MODEL to a Haiku id to run cheaper). Output
is forced into JSON via a single tool the model is required to call, so we never
parse free text. 429/529 are retried with exponential backoff.
"""

from __future__ import annotations

import base64
import os
import random
import time
from dataclasses import dataclass

import anthropic

from .util import log

# Config constant — swap to "claude-haiku-4-5" to run cheaper. (Caller can also
# override per-run via review.py --model / the UI model picker.)
MODEL = "claude-sonnet-4-6"

MAX_TOKENS = 1024
MAX_RETRIES = 5

SYSTEM_PROMPT = (
    "You are reviewing a single frame from a video for visible text errors. "
    "First transcribe the text you can read clearly, then report ONLY genuine "
    "errors: spelling mistakes, typos, grammar errors, or clearly broken "
    "formatting.\n"
    "Hard rules:\n"
    "- If any on-screen text is cut off at the frame edge, partially rendered, "
    "mid-animation, or otherwise incomplete, do NOT report it — a letter missing "
    "because the text is cropped or still animating is not a spelling error. Only "
    "report errors in text that is fully and clearly rendered. Do not guess at "
    "blurry or low-opacity text; if you report something you are not fully certain "
    "of, set confidence to \"low\".\n"
    "- A brand or product name's intentional styling is not an error — ignore "
    "ALL-CAPS, intentional capitalization, and stylized spacing. But DO report a "
    "brand name that is genuinely misspelled or run together (e.g. \"REDBULL\" "
    "should be \"RED BULL\").\n"
    "- The suggested_fix must be the corrected text ONLY — never commentary or "
    "an explanation. If exact_text_seen is already correct, return no error for it."
)

USER_PROMPT = (
    "Review this frame. Report every genuine on-screen text error via the "
    "report_errors tool. If there are no errors, return an empty list."
)

# Forced-output tool: the model MUST call this, so we always get valid JSON.
ERROR_TOOL = {
    "name": "report_errors",
    "description": "Report on-screen text errors found in the frame.",
    "input_schema": {
        "type": "object",
        "properties": {
            "errors": {
                "type": "array",
                "description": "Genuine text errors; empty if the frame is clean.",
                "items": {
                    "type": "object",
                    "properties": {
                        "exact_text_seen": {
                            "type": "string",
                            "description": "The exact on-screen text containing the error.",
                        },
                        "error_type": {
                            "type": "string",
                            "description": "spelling | typo | grammar | formatting",
                        },
                        "suggested_fix": {
                            "type": "string",
                            "description": "The corrected text.",
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "note": {
                            "type": "string",
                            "description": "Short rationale or context. May be empty.",
                        },
                    },
                    "required": [
                        "exact_text_seen", "error_type",
                        "suggested_fix", "confidence", "note",
                    ],
                },
            }
        },
        "required": ["errors"],
    },
}


@dataclass
class FrameErrors:
    """Result of analyzing one frame."""

    errors: list[dict]
    ok: bool = True
    error_message: str | None = None  # set when the call failed after retries


def make_client() -> anthropic.Anthropic:
    """Build the SDK client. API key comes from ANTHROPIC_API_KEY (never hardcoded)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")
    return anthropic.Anthropic()


def _encode(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")


def analyze_frame(
    client: anthropic.Anthropic,
    image_path: str,
    model: str = MODEL,
) -> FrameErrors:
    """Send one frame to Claude and return its structured error list.

    Retries 429 (rate limit) and 529 (overloaded) with exponential backoff +
    jitter. Any other failure after retries is returned as ``ok=False`` so the
    run continues and the bad frame is reported rather than crashing the batch.
    """
    b64 = _encode(image_path)
    delay = 1.0
    last_err: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[ERROR_TOOL],
                tool_choice={"type": "tool", "name": "report_errors"},
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": USER_PROMPT},
                    ],
                }],
            )
            for block in resp.content:
                if block.type == "tool_use" and block.name == "report_errors":
                    errors = block.input.get("errors", []) if isinstance(block.input, dict) else []
                    return FrameErrors(errors=errors)
            # Model didn't call the tool (rare with forced tool_choice).
            return FrameErrors(errors=[])
        except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
            last_err = e
            sleep = delay + random.uniform(0, 0.5)
            log("claude", f"retry {attempt + 1}/{MAX_RETRIES} after {type(e).__name__}; sleep {sleep:.1f}s")
            time.sleep(sleep)
            delay = min(delay * 2, 30)
        except Exception as e:  # noqa: BLE001 — surface, don't crash the batch
            last_err = e
            log("claude", f"non-retryable error on {os.path.basename(image_path)}: {e}")
            break

    return FrameErrors(errors=[], ok=False, error_message=str(last_err) if last_err else "unknown error")
