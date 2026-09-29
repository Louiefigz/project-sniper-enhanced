"""Static font readiness for a built native Short, before any browser work.

Checks that every declared ``@font-face`` source is a staged regular file inside
the project with a recognized font signature that fontconfig can parse, and that
every character of the Short's captions, title and text cues is covered by at
least one declared face (otherwise it would render in an undeclared fallback).
Browser font loading is still verified on real frames during capture.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from captions.caption_font_closure import _covers, _query
from cut_preview_io import bound_json, file_hash

FACE = re.compile(r'@font-face\s*\{([^}]*)\}', re.IGNORECASE)
FIELD = re.compile(r'(font-family|font-weight|src)\s*:\s*([^;]+)', re.IGNORECASE)
URL = re.compile(r'url\(\s*["\']?([^"\')]+?)["\']?\s*\)', re.IGNORECASE)
SIGNATURES = {b'\x00\x01\x00\x00': 'truetype', b'OTTO': 'opentype', b'true': 'truetype',
              b'ttcf': 'collection', b'wOFF': 'woff', b'wOF2': 'woff2'}
SCOPE = 'static font files and glyph coverage only; browser loading is checked on captured frames'
MIN_PHONE_TEXT_PX = 48
DECLARED_SIZE = re.compile(r'font-size\s*:\s*(\d+(?:\.\d+)?)px', re.IGNORECASE)


def html_files(project: Path) -> list[Path]:
    """The entry document and every staged composition, in a stable order."""
    files = [project / 'index.html', *sorted((project / 'compositions').glob('*.html'))]
    return [file for file in files if file.is_file()]


def declared_text_sizes(project: Path, minimum: float = MIN_PHONE_TEXT_PX) -> dict:
    """List declared CSS text sizes below the phone floor at the 1080-wide canvas.

    A review finding only: transforms or hidden elements can change what renders.
    """
    counts: dict[tuple[str, float], int] = {}
    pairs = [(file.relative_to(project).as_posix(), float(value)) for file in html_files(project)
             for value in DECLARED_SIZE.findall(file.read_text(encoding='utf-8'))]
    for key in (pair for pair in pairs if pair[1] < minimum):
        counts[key] = counts.get(key, 0) + 1
    rows = [{'file': file, 'fontPx': size, 'count': count} for (file, size), count in sorted(counts.items())]
    return {'status': 'declared-small-text' if rows else 'no-small-declarations', 'minimumPx': minimum,
            'declarations': rows, 'scope': 'declared CSS font sizes; rendered size can differ; review finding only'}


def declared_faces(project: Path) -> list[dict]:
    """List @font-face declarations in the entry document and mounted compositions."""
    files = html_files(project)
    faces = []
    for file in files:
        for block in FACE.findall(file.read_text(encoding='utf-8')):
            fields = {name.lower(): value.strip() for name, value in FIELD.findall(block)}
            urls = URL.findall(fields.get('src', ''))
            faces.append({'declaredIn': file.relative_to(project).as_posix(),
                          'family': fields.get('font-family', '').strip('\'" '),
                          'weight': fields.get('font-weight', 'normal'), 'urls': urls})
    return faces


def face_state(project: Path, face: dict, tool: str | None) -> tuple[dict, list[dict], list[dict]]:
    """Resolve one face's local sources; return its state, defects and coverage records."""
    defects, sources, records = [], [], []
    for url in face['urls']:
        file = (project / url).resolve()
        if url.startswith(('http:', 'https:', '//')) or not file.is_relative_to(project) or not file.is_file():
            defects.append({'code': 'font-source-missing', 'file': face['declaredIn'], 'reference': url})
            continue
        signature = SIGNATURES.get(file.read_bytes()[:4])
        if signature is None or tool is None:
            defects.append({'code': 'font-source-unreadable', 'file': face['declaredIn'], 'reference': url})
            continue
        sources.append({'url': url, 'format': signature, 'sha256': file_hash(file)})
        records.extend(_query(str(file), tool))
    if not sources:
        defects.append({'code': 'font-face-without-usable-source', 'file': face['declaredIn'],
                        'reference': face['family']})
    families = sorted({name for record in records for name in record['families']})
    return {**face, 'sources': sources, 'families': families}, defects, records


def text_inventory(plan: dict) -> dict[str, str]:
    """Collect every authored string the native canvas and title render."""
    canvas = plan.get('canvas', {})
    captions = [row[5] for row in canvas.get('occurrences', [])]
    captions += [row.get('displayText', '') for row in canvas.get('captionCorrections', [])]
    title = [(plan.get('catalogTitle') or {}).get('copy', {}).get('text', '')]
    title += list((canvas.get('titleCard') or {}).get('lines', []))
    return {'captions': ' '.join(captions), 'title': ' '.join(title),
            'text': ' '.join(row.get('text', '') for row in canvas.get('text', []))}


def uncovered_characters(inventory: dict[str, str], records: list[dict]) -> list[dict]:
    """Report characters no declared face covers, with the lanes that use them."""
    missing: dict[str, set[str]] = {}
    pairs = {(lane, item) for lane, text in inventory.items() for item in text if not item.isspace()}
    for lane, character in pairs:
        if not any(_covers(record, ord(character)) for record in records):
            missing.setdefault(character, set()).add(lane)
    return [{'character': key, 'codepoint': f'U+{ord(key):04X}', 'lanes': sorted(value)}
            for key, value in sorted(missing.items())]


def font_readiness(project: Path) -> dict:
    """Return one static font report; never a claim that fonts loaded or look right.

    Args:
        project: Canonical built native Short project.

    Returns:
        Status ``fonts-ready``, ``defects`` or ``incomplete`` with faces, coverage and defects.
    """
    tool = shutil.which('fc-query')
    faces, defects, records = [], [], []
    for face in declared_faces(project):
        state, problems, coverage = face_state(project, face, tool)
        faces.append(state)
        defects.extend(problems)
        records.extend(coverage)
    inventory = text_inventory(bound_json(project / 'SHORT-PROJECT.json'))
    missing = uncovered_characters(inventory, records) if records else []
    defects.extend({'code': 'glyph-not-covered', 'file': 'SHORT-PROJECT.json', 'reference': row['codepoint'],
                    'lanes': row['lanes']} for row in missing)
    if not faces:
        defects.append({'code': 'no-declared-font-face', 'file': 'index.html', 'reference': ''})
    status = 'incomplete' if tool is None else ('defects' if defects else 'fonts-ready')
    return {'schemaVersion': 1, 'status': status, 'scope': SCOPE, 'faces': faces, 'uncovered': missing,
            'characters': len({item for text in inventory.values() for item in text if not item.isspace()}),
            'defects': defects, 'fontconfigQuery': tool}
