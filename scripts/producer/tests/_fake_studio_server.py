"""A loopback TEST stand-in for pinned Studio's identity and preview routes; no Node process runs.

It answers the routes ``native_handoff_checks.studio_served`` reads, shaped as HyperFrames 0.8.31
answers them. ``rewrites`` names project files it rewrites on load the way Studio's
``persistHfIdsIfNeeded`` (main preview) and ``stampFileHfIds`` (sub-composition preview) do:
a minted ``data-hf-id`` inserted and the file written back.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote


def stamp(file: Path) -> None:
    """Write the file back with one minted selection id, as Studio does for an unstamped element."""
    text = file.read_text()
    file.write_text(text.replace('<p>', '<p data-hf-id="hf-p-0">', 1) if '<p>' in text
                    else text + '<!-- TEST re-serialized -->')


class FakeStudio(ThreadingHTTPServer):
    """One TEST preview server bound to 127.0.0.1 on an ephemeral port."""

    daemon_threads = True

    def __init__(self) -> None:
        """Serve nothing until ``serve`` names the project and the registered PID."""
        super().__init__(('127.0.0.1', 0), Handler)
        self.project: Path | None = None
        self.pid: int | None = None
        self.claimed_dir: str | None = None
        self.compositions = ['index.html', 'compositions/caption.html']
        self.rewrites: set[str] = set()
        self.requests: list[str] = []
        self.after_load: Callable[[], None] | None = None  # runs once the main preview has been served
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        """The ephemeral loopback port."""
        return self.server_address[1]

    def serve(self, project: str, pid: int) -> None:
        """Answer as the Studio process ``pid`` serving ``project``."""
        self.project, self.pid = Path(project), pid

    def close(self) -> None:
        """Stop serving and release the socket."""
        self.shutdown()
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    """GET routes only; anything unknown is a 404."""

    server: FakeStudio

    def do_GET(self) -> None:
        """Route one TEST request."""
        studio, path = self.server, self.path
        studio.requests.append(path)
        name = studio.project.name if studio.project else ''
        base = f'/api/projects/{name}'
        if path == '/__hyperframes_config':
            return self.reply({'isHyperframes': True, 'pid': studio.pid, 'projectName': name,
                               'projectDir': studio.claimed_dir or str(studio.project), 'version': '0.8.31-TEST'})
        if path == base:
            return self.reply({'id': name, 'dir': str(studio.project), 'title': name, 'files': [],
                               'compositions': studio.compositions})
        if path == f'{base}/preview':
            return self.page('index.html')
        if path.startswith(f'{base}/preview/comp/'):
            return self.page(unquote(path.removeprefix(f'{base}/preview/comp/')))
        self.send_error(404)

    def page(self, name: str) -> None:
        """Serve a preview document, first rewriting the project file when configured to."""
        if name in self.server.rewrites:
            stamp(self.server.project / name)
        body = f'<!DOCTYPE html><html><body>TEST preview {name}</body></html>'.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=UTF-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if name == 'index.html' and self.server.after_load:
            self.server.after_load()

    def reply(self, value: dict) -> None:
        """One JSON answer."""
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (stdlib signature)
        """Keep TEST output quiet."""
