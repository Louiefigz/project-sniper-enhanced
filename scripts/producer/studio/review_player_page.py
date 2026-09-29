"""The local review player's page: labeled attempts around the shared playback controller.

The page embeds ``templates/clip-review/playback.mjs`` (the controller review bundles
pin) and is fully inline. Its Content-Security-Policy pins the exact script and style
by hash and allows media and its own playback reports (POST ``/activity`` with the page-load
token the body carries) only to this loopback server, so it cannot load or send anything
elsewhere. A report says the page's video element loaded or played that exact MP4 route; it is
not evidence that anyone watched or listened.
"""
from __future__ import annotations

import base64
from collections import Counter
import hashlib
from html import escape

from studio.native_review_bundle import PLAYER
from studio.review_player_inventory import require

KINDS = {'checked': 'checked for review', 'draft': 'review draft', 'unverified': 'not re-verified',
         'blocked': 'not playable'}
STYLE = ('body{font:16px system-ui,sans-serif;background:#16181b;color:#f2f2f2;margin:24px}h1{font-size:22px}'
         'section{border:2px solid #444;border-radius:8px;padding:12px 16px;margin:0 0 20px;max-width:780px}'
         'section.checked{border-color:#2e7d32}section.draft{border-color:#f9a825}'
         'section.unverified{border-color:#ef6c00}h2{font-size:18px;margin:4px 0}'
         '.label{font-weight:700;font-size:17px;margin:6px 0}.checked .label{color:#81c784}'
         '.draft .label{color:#ffd54f}.unverified .label{color:#ffb74d}.blocked .label{color:#bdbdbd}'
         '.findings li{color:#ffe082}.id,.path,.sha{color:#9e9e9e;font:12px ui-monospace,monospace}'
         'video{display:block;width:100%;max-height:70vh;background:#000}button{font:inherit;padding:4px 10px}')
CONTROLS = """const pageToken=document.body.dataset.pageToken;
document.querySelectorAll('section video').forEach(media=>{
const section=media.closest('section'),status=section.querySelector('[role="status"]');
const report=event=>fetch('/activity',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({token:pageToken,attempt:section.dataset.attempt,route:media.getAttribute('src'),
    event:event.type,currentTime:media.currentTime})}).catch(()=>{});
media.addEventListener('loadeddata',report,{once:true});
media.addEventListener('playing',report);
const playback=new SelectionPlayback(media,event=>{status.textContent=event.message||event.state;});
media.addEventListener('ended',()=>{if(playback.ranges.length)playback.stop('finished');});
section.querySelector('[data-action="play"]').addEventListener('click',()=>
  playback.start([{start:0,end:Number(media.dataset.duration)}],media.getAttribute('src')));
section.querySelector('[data-action="resume"]').addEventListener('click',()=>playback.resume());
section.querySelector('[data-action="reload"]').addEventListener('click',()=>playback.reload());
});"""
SCOPE = ('Labels come from each attempt\'s delivery.json. CHECKED FOR REVIEW means the delivery passed its technical '
         'checks and its receipt chain re-verifies now. This page does not read editorial reviews: whether a checked MP4 '
         'is an editorially approved final is reported by native-review.ts check-final on its FINAL-REVIEW record. A '
         'draft is never final. Only the exact recorded MP4 bytes are served, read-only. Nothing on this page is human '
         'approval or a listening check.')


def shared_player() -> str:
    """Embed the pinned shared controller exactly as review bundles do."""
    source = PLAYER.read_text()
    require(source.count('export class SelectionPlayback') == 1, 'shared review player contract changed')
    player = source.replace('export class SelectionPlayback', 'class SelectionPlayback', 1)
    require('</script' not in player.lower(), 'shared player cannot be embedded safely')
    return player


def source_hash(text: str) -> str:
    """CSP source expression for one exact inline element body."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def policy(script: str) -> str:
    """No network origin at all: only this server's media and the exact inline code."""
    return (f"default-src 'none'; media-src 'self'; connect-src 'self'; script-src {source_hash(script)}; "
            f"style-src {source_hash(STYLE)}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def player_markup(row: dict) -> str:
    """Video, recovery controls and the exact bytes it serves."""
    return (f'<video controls preload="metadata" playsinline data-duration="{row["durationSeconds"]!r}" '
            f'src="{escape(row["route"])}"></video><p><button data-action="play">Play from start</button> '
            '<button data-action="resume">Resume</button> <button data-action="reload">Reload video</button></p>'
            f'<p role="status">Ready</p><p class="sha">SHA-256 {escape(row["sha256"])} · {row["bytes"]} bytes · '
            f'{escape(row["file"])}</p>')


def card(row: dict) -> str:
    """One attempt: its label first, then recorded evidence, then the player when playable."""
    parts = [f'<section class="{escape(row["kind"])}" data-attempt="{escape(row["id"])}"><h2>{escape(row["title"])} '
             f'<span class="id">{escape(row["id"])}</span></h2><p class="label">{escape(row["label"])}</p>']
    if row.get('detail'):
        parts.append(f'<p>{escape(row["detail"])}</p>')
    if row['findings']:
        parts.append('<ul class="findings">' + ''.join(
            f'<li>{escape(item["severity"])} {escape(item["code"])}: {escape(item["message"])} '
            f'Required: {escape(item["requiredAction"])}</li>' for item in row['findings']) + '</ul>')
    if row['notes']:
        parts.append('<ul>' + ''.join(f'<li>{escape(note)}</li>' for note in row['notes']) + '</ul>')
    if row['playable']:
        parts.append(player_markup(row))
    return ''.join(parts) + f'<p class="path">{escape(row["export"])}</p></section>'


def page(rows: list[dict], checked_at: str, token: str) -> tuple[str, str]:
    """Return the complete page (carrying this load's report token) and the Content-Security-Policy that pins it."""
    script = shared_player() + '\n' + CONTROLS
    counts = Counter(row['kind'] for row in rows)
    summary = ', '.join(f'{counts[kind]} {text}' for kind, text in KINDS.items() if counts[kind])
    document = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>Delivered Shorts review</title><style>{STYLE}</style></head>'
                f'<body data-page-token="{escape(token)}">'
                f'<h1>Delivered Shorts — local review</h1><p>{len(rows)} attempts: {escape(summary)}. '
                f'Checked {escape(checked_at)}.</p><p>{escape(SCOPE)}</p>'
                + ''.join(card(row) for row in rows) + f'<script>{script}</script></body></html>')
    return document, policy(script)
