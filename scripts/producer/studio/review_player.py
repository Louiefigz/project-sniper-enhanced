#!/usr/bin/env python3
"""Serve delivered native MP4s on a loopback-only, clearly labeled local review page.

  review_player.py serve (--manifest FILE | --attempt ID=/abs/attempt ...) [--port N] [--serve-seconds S]
  review_player.py list  (--manifest FILE | --attempt ID=/abs/attempt ...)

``--manifest`` takes the review-bundle manifest schema (``{"schemaVersion": 1,
"compositions": [{"id", "title", "export"}]}``); ``--attempt`` adds ``ID=folder`` rows.
The server binds 127.0.0.1 only, answers GET/HEAD for ``/``, ``/inventory.json`` (the same
labels as JSON plus this server's pid/port/start identity and its per-attempt activity log,
read by ``native_handoff.py``) and ``/media/<id>.mp4`` alone, plus one POST, ``/activity``, where
its own page reports its video element's playback (``review_player_activity``); it refuses
foreign Host headers and origins, supports single byte ranges for seeking and
opens every MP4 read-only. It never writes, links or re-encodes media. It serves until
interrupted, or for ``--serve-seconds`` when the caller passes that bound.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from cut_preview_io import file_identity
from studio.review_player_activity import MAX_REPORT_BYTES, ActivityLog
from studio.review_player_inventory import Attempt, Evaluator, read_attempts, require
from studio.review_player_page import page

HOST = '127.0.0.1'
MEDIA_ROUTE = re.compile(r'/media/([A-Za-z][A-Za-z0-9_-]{0,63})\.mp4\Z')
RANGE = re.compile(r'bytes=([0-9]*)-([0-9]*)\Z')
CHUNK = 256 * 1024
INVENTORY_FIELDS = ('id', 'title', 'export', 'kind', 'label', 'playable', 'sha256', 'bytes', 'route',
                    'receipts', 'findings')
BASE_HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                'Cross-Origin-Resource-Policy': 'same-origin', 'X-Frame-Options': 'DENY'}


class RangeError(ValueError):
    """An unsatisfiable, malformed or multi-part Range header."""


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """One inclusive byte span for seeking, or None for the whole file."""
    if header is None:
        return None
    match = RANGE.fullmatch(header.strip())
    if match is None or not (match[1] or match[2]) or size <= 0:
        raise RangeError(header)
    if not match[1]:
        if int(match[2]) == 0:
            raise RangeError(header)
        return max(0, size - int(match[2])), size - 1
    start, end = int(match[1]), min(int(match[2]), size - 1) if match[2] else size - 1
    if start > end:
        raise RangeError(header)
    return start, end


class ReviewPlayer(ThreadingHTTPServer):
    """Loopback server whose inventory snapshot is replaced atomically on each page load."""

    daemon_threads = True

    def __init__(self, attempts: list[Attempt], port: int) -> None:
        """Bind 127.0.0.1 only and evaluate every attempt before accepting requests."""
        super().__init__((HOST, port), Handler)
        self.attempts, self.evaluator = attempts, Evaluator()
        self.snapshot: dict[str, dict] = {}
        self.checked_at = ''
        self.identity = {'pid': os.getpid(), 'port': self.server_address[1],
                         'startedAt': datetime.now(timezone.utc).isoformat(timespec='microseconds')}
        self.activity = ActivityLog()
        self.refresh()

    def refresh(self) -> list[dict]:
        """Re-read every attempt's receipts; hashes and admissions are cached by identity."""
        rows = self.evaluator.inventory(self.attempts)
        self.snapshot = {row['id']: row for row in rows}
        self.checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        return rows

    def hosts(self) -> set[str]:
        """The only Host values a loopback page can legitimately send."""
        port = self.server_address[1]
        return {f'{HOST}:{port}', f'localhost:{port}'}


class Handler(BaseHTTPRequestHandler):
    """GET/HEAD for the page and listed playable MP4s; everything else is refused."""

    server: ReviewPlayer
    protocol_version = 'HTTP/1.1'
    timeout = 60

    def version_string(self) -> str:
        """Name the server without advertising the interpreter version."""
        return 'SniperReviewPlayer'

    def do_GET(self) -> None:
        """Serve the page or one exact MP4 range."""
        self.route()

    def do_HEAD(self) -> None:
        """Headers only, with the same routing and checks."""
        self.route()

    def refuse_method(self) -> None:
        """Nothing on this server changes state."""
        self.reply(405, b'Only GET, HEAD and the page\'s own POST /activity are served.\n', {'Allow': 'GET, HEAD, POST'})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = refuse_method

    def do_POST(self) -> None:
        """The page's own playback report: this origin, bounded JSON, a token it was issued, a listed route."""
        host = self.headers.get('Host')
        if host not in self.server.hosts() or self.headers.get('Origin') != f'http://{host}' or self.path != '/activity':
            return self.reply(403, b'Loopback review player: only its own page reports playback.\n')
        size = self.headers.get('Content-Length', '')
        if not (self.headers.get('Content-Type') or '').startswith('application/json') or not size.isdigit() \
                or int(size) > MAX_REPORT_BYTES:
            return self.reply(400, b'A playback report is small JSON.\n')
        try:
            report = json.loads(self.rfile.read(int(size)))
        except ValueError:
            return self.reply(400, b'A playback report is JSON.\n')
        problem = self.server.activity.refusal(report, self.server.snapshot)
        if problem:
            return self.reply(400, (problem + '\n').encode())
        self.server.activity.playback_report(report, self.headers.get('User-Agent') or '')
        return self.reply(204, b'')

    def route(self) -> None:
        """Map a loopback request to the page or a listed playable attempt, never to a path."""
        target = urlsplit(self.path)
        if self.headers.get('Host') not in self.server.hosts():
            return self.reply(403, b'Loopback review player: unexpected Host header.\n')
        if target.scheme or target.netloc or target.query or target.fragment:
            return self.reply(404, b'Not found.\n')
        if target.path == '/':
            rows = self.server.refresh()
            token = self.server.activity.page_load(self.headers.get('User-Agent') or '')
            document, policy = page(rows, self.server.checked_at, token)
            return self.reply(200, document.encode(), {'Content-Type': 'text/html; charset=utf-8',
                                                       'Content-Security-Policy': policy})
        if target.path == '/inventory.json':
            rows = [{key: row.get(key) for key in INVENTORY_FIELDS} for row in self.server.refresh()]
            document = {'schemaVersion': 2, 'checkedAt': self.server.checked_at, 'server': self.server.identity,
                        'attempts': rows, 'activity': self.server.activity.document()}
            return self.reply(200, json.dumps(document).encode(), {'Content-Type': 'application/json'})
        match = MEDIA_ROUTE.fullmatch(target.path)
        row = self.server.snapshot.get(match[1]) if match else None
        if row is None or not row['playable']:
            return self.reply(404, b'Not found.\n')
        self.server.activity.media_request(row['id'], {'method': self.command, 'path': target.path,
                                                       'range': self.headers.get('Range'),
                                                       'userAgent': (self.headers.get('User-Agent') or '')[:300]})
        try:
            self.media(row)
        except OSError:
            self.reply(410, b'This MP4 is no longer readable; reload the page.\n')

    def media(self, row: dict) -> None:
        """Serve the verified bytes read-only; any identity change since verification refuses."""
        descriptor = os.open(row['file'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if list(file_identity(info)) != row['identity']:
                return self.reply(409, b'This MP4 changed after it was verified; reload the page.\n')
            try:
                span = byte_range(self.headers.get('Range'), info.st_size)
            except RangeError:
                return self.reply(416, b'', {'Content-Range': f'bytes */{info.st_size}'})
            start, end = span or (0, info.st_size - 1)
            headers = {'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes', 'Content-Length': str(end - start + 1)}
            if span:
                headers['Content-Range'] = f'bytes {start}-{end}/{info.st_size}'
            self.head(206 if span else 200, headers)
            if self.command == 'GET':
                self.stream(descriptor, start, end)
        finally:
            os.close(descriptor)

    def stream(self, descriptor: int, start: int, end: int) -> None:
        """Copy the inclusive span with positioned reads; a closed tab just ends the copy."""
        position = start
        try:
            while position <= end and (chunk := os.pread(descriptor, min(CHUNK, end - position + 1), position)):
                self.wfile.write(chunk)
                position += len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def head(self, code: int, headers: dict[str, str]) -> None:
        """Status line plus the fixed privacy headers."""
        self.send_response(code)
        for key, value in {**BASE_HEADERS, **headers}.items():
            self.send_header(key, value)
        self.end_headers()

    def reply(self, code: int, payload: bytes, headers: dict[str, str] | None = None) -> None:
        """A complete small response; HEAD receives the headers only."""
        self.head(code, {'Content-Type': 'text/plain; charset=utf-8', **(headers or {}),
                         'Content-Length': str(len(payload))})
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def log_request(self, code: int | str = '-', size: int | str = '-') -> None:
        """Log refusals and errors only; routine page and range requests stay quiet."""
        if isinstance(code, int) and code >= 400:
            super().log_request(code, size)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (stdlib signature)
        """One compact line per logged request on stderr."""
        sys.stderr.write('review-player: ' + format % args + '\n')


def serve(attempts: list[Attempt], port: int, seconds: float | None) -> None:
    """Serve until interrupted, or until the caller's explicit bound elapses."""
    require(type(port) is int and 0 <= port <= 65535, 'port must be between 0 and 65535')
    require(seconds is None or 0 < seconds <= 7 * 86400, '--serve-seconds must be a positive bound')
    server = ReviewPlayer(attempts, port)
    url = f'http://{HOST}:{server.server_address[1]}/'
    print(json.dumps({'status': 'serving', 'url': url, 'pid': os.getpid(), 'attempts': [
        {key: row.get(key) for key in ('id', 'label', 'playable', 'route')} for row in server.snapshot.values()]}),
        flush=True)
    if seconds is not None:
        timer = threading.Timer(seconds, server.shutdown)
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print(json.dumps({'status': 'stopped', 'url': url}), flush=True)


def main() -> None:
    """List or serve the named attempts."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('serve', 'list'))
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--attempt', action='append', default=[], metavar='ID=/absolute/attempt-folder')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--serve-seconds', type=float)
    args = parser.parse_args()
    attempts = read_attempts(args.manifest, args.attempt)
    if args.action == 'list':
        print(json.dumps({'attempts': Evaluator().inventory(attempts)}, indent=2))
        return
    serve(attempts, args.port, args.serve_seconds)


if __name__ == '__main__':
    main()
