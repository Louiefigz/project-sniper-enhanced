"""Inline bounded local body scripts before Studio scopes each composition.

External classic scripts otherwise execute outside the per-instance wrapper,
and root-relative URLs address Studio itself rather than the motion catalog.
Inlining the admitted source first lets the existing timeline-key transform
and upstream scoped-document wrapper handle it exactly like authored inline JS.
"""
from __future__ import annotations

from html.parser import HTMLParser
from functools import lru_cache
import json
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
import re

from cut_preview_io import read_bytes
from headless.source_closure import _local_reference, _references
from headless.process_runner import ProcessRequest, run_text
from studio import StudioProjectError
from studio.project_assets import _sanitized_js
from studio.comp_hf_ids import _node

MOTION_ROOT = Path(__file__).resolve().parents[3] / 'templates' / 'motion'
_SCRIPTS = re.compile(r'<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>', re.I | re.S)
_MAX_SCRIPT_BYTES = 1024 * 1024
STYLE_SCOPE = 'catalog-root-style-v1'


class _ScriptAttributes(HTMLParser):
    """Read exact attributes without accepting duplicate script-source keys."""

    def __init__(self, attributes: str) -> None:
        super().__init__(convert_charrefs=True)
        self.attributes: list[tuple[str, str | None]] = []
        self.feed('<script' + attributes + '></script>')
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Retain the parser's ordered attributes for strict admission."""
        if tag != 'script' or self.attributes:
            raise StudioProjectError('unsupported body-script tag anatomy')
        self.attributes = attrs


def _inline_script(match: re.Match[str]) -> str:
    """Keep inline JS untouched; admit only one plain local classic dependency."""
    attributes = _ScriptAttributes(match.group('attrs')).attributes
    if not any(name == 'src' for name, _ in attributes):
        return match.group(0)
    if len(attributes) != 1 or attributes[0][0] != 'src' or match.group('body').strip():
        raise StudioProjectError('body script requires only src; async/module/inline fallback is unsupported')
    raw = attributes[0][1]
    try:
        relative = _local_reference(raw or '')
        if relative is None or not relative.endswith('.js'):
            raise ValueError('body script must name a local .js file')
        data = read_bytes(MOTION_ROOT / relative, _MAX_SCRIPT_BYTES)
        _references(relative, data)  # Same no-remote/ES-module closure policy as the renderer.
        source = _sanitized_js(data.decode('utf-8'))
    except (OSError, RuntimeError, ValueError) as error:
        raise StudioProjectError('Studio body-script dependency refused: ' + str(error)) from error
    return '<script>\n' + source + '\n</script>'


def inline_local_body_scripts(body: str) -> str:
    """Inline each admitted body dependency at its original execution position."""
    return _SCRIPTS.sub(_inline_script, body)


@lru_cache(maxsize=128)
def bind_instance_styles(body: str, root_id: str) -> str:
    """Scope page-style accesses per catalog body, retaining literal/comment bytes.

    Reuse the SDK's installed JS parser and the existing bounded Node runner.
    Cache before per-instance re-keying, so repeated cards do not launch Node.
    Existing saved projects are never rewritten by this source transform.
    """
    if not re.search(r'document\s*\.\s*(?:documentElement|body)\s*\.\s*style', body):
        return body
    matches = list(_SCRIPTS.finditer(body))
    raw = json.dumps({'rootId': root_id, 'scripts': [m.group('body') for m in matches]})
    if len(raw.encode()) > 4 * _MAX_SCRIPT_BYTES:
        raise StudioProjectError('composition style request exceeds4MiB')
    completed = _run_style_parser(raw.encode())
    if completed.returncode or completed.stderr:
        raise StudioProjectError('composition style parser refused: ' + completed.stderr[:500])
    response = json.loads(completed.stdout)
    if set(response) != {'scripts'} or not isinstance(response['scripts'], list) \
            or len(response['scripts']) != len(matches) \
            or any(not isinstance(value, str) for value in response['scripts']):
        raise StudioProjectError('invalid composition style parser response')
    for match, source in reversed(list(zip(matches, response['scripts']))):
        body = body[:match.start('body')] + source + body[match.end('body'):]
    return body


def _run_style_parser(raw: bytes) -> subprocess.CompletedProcess[str]:
    """Use the runner's empty-stdin contract and one bounded owned input file."""
    node = _node()
    script = Path(__file__).with_name('comp_style_scope.mjs')
    with tempfile.TemporaryDirectory(prefix='sniper-style-scope-') as temporary:
        target = Path(temporary).resolve() / 'request.json'
        with target.open('xb') as handle:
            handle.write(raw)
        request = ProcessRequest((node, str(script), '--batch', str(target),
            hashlib.sha256(raw).hexdigest()), '', str(MOTION_ROOT.parents[1]),
            {'PATH': os.path.dirname(node), 'LANG': 'C.UTF-8', 'TZ': 'UTC'},
            10, max_output_bytes=8 * _MAX_SCRIPT_BYTES)
        return run_text(request)


def bind_mounted_duration(body: str) -> str:
    """Read timing from the surviving composition root in either SDK layout.

    SDK 0.8.31 strips timing attributes from the inner authored root when it
    mounts a template. Its closest composition is then the live host, whose
    duration includes native timeline edits. Standalone roots match themselves.
    Do not copy timing onto the inner node or cache a stale duration literal.
    """
    return _SCRIPTS.sub(lambda match: match.group(0).replace(
        'root.dataset.duration',
        'root.closest("[data-composition-id]").dataset.duration'), body)
