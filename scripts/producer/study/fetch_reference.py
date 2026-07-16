#!/usr/bin/env python3
"""fetch_reference — pull ONE reference video via the yt-dlp CLI.

The style system studies polished example videos the operator admires; most live
on YouTube / Instagram / TikTok, so this wraps the ``yt-dlp`` binary (the
documented fetch wire — with an EXPLICITLY OPTED-IN chrome-cookie retry for
login/age-gated videos) to download a single video into a target directory under
``<workspace>/_references/``. The download itself is entirely yt-dlp's; this file
only turns its progress into NDJSON events (the same ``--server`` stdout contract
the other producer workers use), preserves English VTT captions, and gates the
cookie retry. It does NOT reinvent any download logic.

CLI:
    fetch_reference.py --url URL --out-dir DIR [--allow-cookies]
                       [--cookies-browser chrome]

Events (one JSON object per stdout line):
    {"event":"status","stage":"start","cookies":bool}
    {"event":"progress","percent":<float 0-100>}
    {"event":"status","stage":"retry-cookies"}      # auth wall → retrying
    {"event":"done","video":"<abs path>","title":"..."}
    {"event":"error","message":"..."}

The URL is passed as a single argv element after ``--`` (never shell-interpolated,
never option-injectable); the Next.js route validates http/https before spawning.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
_DEBUG = os.environ.get("SNIPER_DEBUG", "1") != "0"
MAX_REFERENCE_BYTES = 2 * 1024 ** 3
MIN_FREE_BYTES = 5 * 1024 ** 3
MAX_DURATION_S = 3600.0
_ACTIVE_PROC: subprocess.Popen[str] | None = None

# yt-dlp progress token — a controlled machine string via --progress-template,
# so we parse yt-dlp's OWN percent rather than scraping the human [download] bar.
_PROGRESS_TAG = "SNIPER_PROGRESS"

# Substrings in yt-dlp's error output that mean "this needs your browser session"
# (login / private / age / members-only). A hit can trigger an explicitly allowed retry.
_AUTH_HINTS = (
    "sign in", "log in", "login", "private", "age", "confirm your age",
    "members-only", "cookie", "authenticat", "account", "not available",
)


def _emit(event: str, **fields) -> None:
    """One NDJSON event line on stdout (the --server contract)."""
    print(json.dumps({"event": event, **fields}), flush=True)


def _log(msg: str) -> None:
    """[SNIPER:fetch] trace to stderr, gated by SNIPER_DEBUG (mirrors siblings)."""
    if _DEBUG:
        print(f"[SNIPER:fetch] {msg}", file=sys.stderr, flush=True)


def _terminate_active(_signum, _frame) -> None:
    """Forward route cancellation to yt-dlp instead of orphaning it."""
    if _ACTIVE_PROC and _ACTIVE_PROC.poll() is None:
        _ACTIVE_PROC.terminate()
        try:
            _ACTIVE_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ACTIVE_PROC.kill()
    raise SystemExit(143)


def resolve_ytdlp() -> str | None:
    """The yt-dlp binary: PATH first, then the common Homebrew/local locations
    (the Next dev server's PATH may omit /opt/homebrew/bin)."""
    found = shutil.which("yt-dlp")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def build_argv(ytdlp: str, out_dir: str, cookies_browser: str | None) -> list[str]:
    """The yt-dlp argv (URL appended by the caller after ``--``)."""
    argv = [
        ytdlp,
        "--no-playlist",          # a reference is one video, never a channel dump
        "--no-color",
        "--newline",              # one progress line each, not \r overwrites
        "--restrict-filenames",   # ascii-safe filenames
        "--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--max-filesize", str(MAX_REFERENCE_BYTES),
        "--match-filter", f"duration <=? {int(MAX_DURATION_S)}",
        "--remux-video", "mp4",   # normalize container so ONE .mp4 lands
        "--write-subs",            # preserve word-timed English captions for study
        "--write-auto-subs",
        "--sub-langs", "en.*,en",
        "--sub-format", "vtt",
        "--progress-template", f"download:{_PROGRESS_TAG} %(progress._percent_str)s",
        "-o", os.path.join(out_dir, "%(title).80s.%(ext)s"),
    ]
    if cookies_browser:
        argv += ["--cookies-from-browser", cookies_browser]
    return argv


def _parse_percent(line: str) -> float | None:
    """Percent from a ``SNIPER_PROGRESS  42.0%`` line, or None."""
    if not line.startswith(_PROGRESS_TAG):
        return None
    token = line[len(_PROGRESS_TAG):].strip().rstrip("%").strip()
    try:
        return float(token)
    except ValueError:
        return None


def run_once(argv: list[str], url: str) -> tuple[int, str, bool]:
    """Run yt-dlp once, streaming progress events. Returns
    (returncode, tail_of_output, saw_auth_wall)."""
    global _ACTIVE_PROC
    proc = subprocess.Popen(
        [*argv, "--", url],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge so error text is in the one stream
        text=True,
        bufsize=1,
    )
    _ACTIVE_PROC = proc
    tail: list[str] = []
    saw_auth = False
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        percent = _parse_percent(line)
        if percent is not None:
            _emit("progress", percent=percent)
            continue
        if not line.strip():
            continue
        _log(line)
        tail.append(line)
        if len(tail) > 40:
            tail.pop(0)
        low = line.lower()
        if "error" in low and any(hint in low for hint in _AUTH_HINTS):
            saw_auth = True
    proc.wait()
    _ACTIVE_PROC = None
    return proc.returncode, "\n".join(tail), saw_auth


def find_video(out_dir: str) -> str | None:
    """The newest video file in out_dir (the reference dir is fresh → one file)."""
    if not os.path.isdir(out_dir):
        return None
    hits = [
        os.path.join(out_dir, n)
        for n in os.listdir(out_dir)
        if os.path.splitext(n)[1].lower() in VIDEO_EXTS
    ]
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


def find_transcript(out_dir: str) -> str | None:
    """Newest English VTT downloaded beside the reference, when available."""
    if not os.path.isdir(out_dir):
        return None
    hits = [os.path.join(out_dir, name) for name in os.listdir(out_dir)
            if name.lower().endswith(".vtt")]
    return max(hits, key=os.path.getmtime) if hits else None


def probe_duration(video: str) -> float | None:
    """Duration from ffprobe, or None when the media cannot be verified."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return float(proc.stdout.strip()) if proc.returncode == 0 else None
    except ValueError:
        return None


def validate_download(video: str) -> str | None:
    """Return an operator-readable bound violation, else None."""
    size = os.path.getsize(video)
    if size > MAX_REFERENCE_BYTES:
        return f"reference is {size} bytes; maximum is {MAX_REFERENCE_BYTES}"
    duration = probe_duration(video)
    if duration is None:
        return "downloaded reference duration could not be verified with ffprobe"
    if duration > MAX_DURATION_S:
        return f"reference is {duration:.1f}s; maximum is {MAX_DURATION_S:.0f}s"
    return None


def fetch(url: str, out_dir: str, cookies_browser: str,
          allow_cookies: bool = False) -> int:
    """Download url; browser cookies are used only with explicit permission."""
    ytdlp = resolve_ytdlp()
    if not ytdlp:
        _emit("error", message="yt-dlp is not installed (not found on PATH). "
              "Install it: brew install yt-dlp")
        return 1

    os.makedirs(out_dir, exist_ok=True)
    if shutil.disk_usage(out_dir).free < MIN_FREE_BYTES:
        _emit("error", message="less than 5 GiB is free; reference download was not started")
        return 1
    _emit("status", stage="start", cookies=False)
    code, tail, auth = run_once(build_argv(ytdlp, out_dir, None), url)

    if code != 0 and auth and allow_cookies:
        _log(f"auth wall detected; retrying with --cookies-from-browser {cookies_browser}")
        _emit("status", stage="retry-cookies")
        code, tail, _ = run_once(build_argv(ytdlp, out_dir, cookies_browser), url)

    if code != 0 and auth and not allow_cookies:
        _emit("error", message="This reference requires authentication. Retry with "
              "allowCookies=true only if you want yt-dlp to read browser cookies.")
        return 1

    if code != 0:
        _emit("error", message=f"yt-dlp failed (exit {code}). {tail[-600:]}".strip())
        return 1

    video = find_video(out_dir)
    if not video:
        _emit("error", message="yt-dlp reported success but no video file landed "
              f"in {out_dir}")
        return 1
    violation = validate_download(video)
    if violation:
        _emit("error", message=violation)
        return 1

    title = os.path.splitext(os.path.basename(video))[0]
    transcript = find_transcript(out_dir)
    _emit("done", video=os.path.abspath(video), title=title,
          transcript=os.path.abspath(transcript) if transcript else None)
    return 0


def main() -> int:
    signal.signal(signal.SIGTERM, _terminate_active)
    signal.signal(signal.SIGINT, _terminate_active)
    parser = argparse.ArgumentParser(
        description="Fetch a reference video via yt-dlp → NDJSON events on stdout")
    parser.add_argument("--url", required=True, help="video URL (https)")
    parser.add_argument("--out-dir", required=True, help="target reference directory")
    parser.add_argument("--cookies-browser", default="chrome",
                        help="browser to pull cookies from on an auth wall (default chrome)")
    parser.add_argument("--allow-cookies", action="store_true",
                        help="allow an auth-wall retry using browser cookies")
    args = parser.parse_args()

    if not args.url.startswith("https://"):
        _emit("error", message="url must use https")
        return 1
    try:
        return fetch(args.url, args.out_dir, args.cookies_browser,
                     allow_cookies=args.allow_cookies)
    except OSError as exc:
        _emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
