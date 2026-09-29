"""What the review player observed, per attempt: page loads, media requests and the page's own playback reports.

Every page load gets a fresh token that the page carries (``data-page-token``). Media requests are kept per
attempt, only for that attempt's exact MP4 route; 404s, favicon and any other path are never recorded (P-A).
An HTTP range request proves only that some client asked for the bytes ("media requested"): ``curl`` does that
as well as a browser, so it is never visibility evidence (operator review item #4).

Visibility evidence is the served page's own playback activity: its script POSTs ``/activity`` when that
attempt's ``<video>`` element fires ``loadeddata`` or ``playing``, naming the attempt, its exact route, the
element's time and the page-load token this server issued. A report is admitted only for a token issued by a page
load, a listed playable attempt and its own route, from this server's own origin, as small bounded JSON.
What this still cannot prove: that a person watched, that the window was visible or unobscured, that audio was
audible or that playback continued past the reported moment. A local program that fetches the page can imitate
the report. It is recorded as page-reported playback, never as human review, listening or approval.
"""
from __future__ import annotations

import math
import secrets
import threading
from collections import deque
from datetime import datetime, timezone

PAGE_LOADS, PER_ATTEMPT = 64, 64
EVENTS = ('loadeddata', 'playing')
REPORT_KEYS = {'token', 'attempt', 'route', 'event', 'currentTime'}
MAX_REPORT_BYTES = 2048


def now() -> str:
    """Wall-clock evidence time."""
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class ActivityLog:
    """Bounded, thread-safe per-attempt observations of one review-player server."""

    def __init__(self) -> None:
        """Empty logs; page tokens live only as long as this server."""
        self.lock = threading.Lock()
        self.pages: deque[dict] = deque(maxlen=PAGE_LOADS)
        self.media: dict[str, deque[dict]] = {}
        self.playback: dict[str, deque[dict]] = {}

    def page_load(self, user_agent: str) -> str:
        """Record one page load and return the token that page carries."""
        token = secrets.token_hex(16)
        with self.lock:
            self.pages.append({'time': now(), 'token': token, 'userAgent': user_agent[:300]})
        return token

    def media_request(self, attempt: str, request: dict) -> None:
        """Record one request of an attempt's exact MP4 route ('media requested', never visibility)."""
        with self.lock:
            self.media.setdefault(attempt, deque(maxlen=PER_ATTEMPT)).append({'time': now(), **request})

    def refusal(self, report: object, rows: dict[str, dict]) -> str | None:
        """Why a playback report cannot be admitted, or None."""
        if not isinstance(report, dict) or set(report) != REPORT_KEYS:
            return f'a playback report carries exactly {sorted(REPORT_KEYS)}'
        row = rows.get(report['attempt']) if isinstance(report['attempt'], str) else None
        time = report['currentTime']
        if row is None or not row.get('playable') or report['route'] != row.get('route'):
            return 'a playback report names a listed playable attempt and its own media route'
        if report['event'] not in EVENTS or type(time) not in (int, float) or not math.isfinite(time) or time < 0:
            return f'a playback report names one of {list(EVENTS)} and a finite element time'
        with self.lock:
            if not any(page['token'] == report['token'] for page in self.pages):
                return 'a playback report carries a token this server issued with a page load'
        return None

    def playback_report(self, report: dict, user_agent: str) -> None:
        """Record one admitted page-reported playback event."""
        entry = {'time': now(), 'token': report['token'], 'event': report['event'], 'route': report['route'],
                 'currentTime': float(report['currentTime']), 'userAgent': user_agent[:300]}
        with self.lock:
            self.playback.setdefault(report['attempt'], deque(maxlen=PER_ATTEMPT)).append(entry)

    def document(self) -> dict:
        """The logs as /inventory.json reports them."""
        with self.lock:
            ids = sorted(set(self.media) | set(self.playback))
            return {'pages': list(self.pages), 'attempts': {key: {
                'mediaRequests': list(self.media.get(key, ())), 'playback': list(self.playback.get(key, ()))}
                for key in ids}}
