"""Write and cold-read isolated native long-form projects using selected media."""
from __future__ import annotations

from pathlib import Path
import shutil

from cut_preview_io import bound_json, file_hash, read_bytes, write_new
from edit.selected_sources import read_package
from studio.long_sources_html import MediaParser, inspect_html, number, transform
from studio.native_preflight_inputs import source_state
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, require, verify_pins

MANIFEST = 'LONG-SOURCES.json'
VIDEO_SUFFIXES = {'.mp4', '.mov', '.m4v'}


def hash_file(file: Path) -> str:
    """Use the existing bounded regular-file hash, including large originals."""
    return file_hash(file, MAX_NATIVE_FILE_BYTES)


def project_html(project: Path) -> str:
    """Preserve authored newlines as well as HTML outside the mapped attributes."""
    return read_bytes(project / 'index.html', 8 * 1024 ** 2).decode('utf-8')


def project_inputs(project: Path) -> dict:
    """Bind the existing project before any preparation; never adopt a partial prior copy."""
    snapshot = source_state(project)
    require(MANIFEST not in snapshot['files'], 'reuse the original project with --reuse-stage for visual revisions')
    text = project_html(project)
    root, media = inspect_html(text)
    paths = {name: project / name for name in snapshot['files']}
    require(all(row.attributes['src'] in paths for row in media), 'native long-form media is missing')
    for name, file in paths.items():
        if name != 'index.html' and file.suffix.lower() in {'.html', '.htm'}:
            require(not MediaParser(file.read_text()).media,
                    'long-form preparation currently requires video/audio on the root timeline')
    pins = {str(file): hash_file(file) for file in paths.values()}
    bindings, preserved = media_bindings(project, media, root, pins)
    require(bool(bindings), 'long-form project has no supported picture source')
    assert_literal_references(paths, media, text, bindings)
    return {'project': str(project), 'files': list(paths), 'pins': pins,
            'bindings': bindings, 'preservedProgramAudio': preserved,
            'canvas': {key: root.get(key) for key in ('data-width', 'data-height', 'data-duration', 'data-fps')}}


def media_bindings(project: Path, media: list, root: dict, pins: dict) -> tuple[dict, list]:
    """Extract only selected MP4/MOV picture ranges; preserve an existing program master."""
    bindings, preserved = {}, []
    for row in media:
        attrs, file = row.attributes, row.attributes['src']
        if Path(file).suffix.lower() in VIDEO_SUFFIXES:
            sha = pins[str(project / file)]
            bindings[file] = {'file': f'assets/{sha}.mp4', 'path': str(project / file), 'sha256': sha}
            continue
        require(row.kind == 'audio' and Path(file).suffix.lower() == '.wav'
                and number(attrs.get('data-media-start', '0')) == 0 and number(attrs['data-start']) == 0
                and number(attrs['data-duration']) == number(root['data-duration']),
                'standalone narration must be the unchanged complete-program WAV; ranged audio needs explicit preparation')
        preserved.append({'id': attrs['id'], 'file': file, 'sha256': pins[str(project / file)]})
    return bindings, preserved


def assert_literal_references(paths: dict, media: list, text: str, bindings: dict) -> None:
    """Reject hidden/dynamic uses of replaced files instead of breaking a working scene."""
    without_media = text
    for row in reversed(media):
        without_media = without_media[:row.offset] + without_media[row.offset + len(row.tag):]
    for name, file in paths.items():
        if file.suffix.lower() not in {'.html', '.htm', '.css', '.js', '.json'}:
            continue
        content = without_media if name == 'index.html' else file.read_text()
        require(not any(source in content for source in bindings),
                f'replaced source has an additional reference in {name}; explicit adaptation is required')


def selection(inputs: dict) -> dict:
    """Project root media supplies exact ranges; overlapping/repeated views share clips."""
    project = Path(inputs['project'])
    _root, media = inspect_html(project_html(project))
    bindings = inputs['bindings']
    ranges = [{'sourceFile': bindings[row.attributes['src']]['file'],
               'start': float(number(row.attributes.get('data-media-start', '0'))),
               'end': float(number(row.attributes.get('data-media-start', '0')) + number(row.attributes['data-duration']))}
              for row in media if row.attributes['src'] in bindings]
    unique = {(row['sourceFile'], row['start'], row['end']): row for row in ranges}
    sources = {row['file']: row for row in bindings.values()}
    return {'schemaVersion': 1, 'handleSeconds': 1, 'sources': list(sources.values()), 'ranges': list(unique.values())}


def mapped_files(inputs: dict, result: dict) -> tuple[str, list, dict]:
    """Reconstruct executable HTML and its exact physical asset inventory."""
    expected = {row['file']: row['sha256'] for row in inputs['bindings'].values()}
    require({row['file']: row['sha256'] for row in result['selection']['sources']} == expected,
            'prepared package substituted or omitted a long-form source')
    project = Path(inputs['project'])
    html, mappings = transform(project_html(project), inputs['bindings'], result)
    files = {name: project / name for name in inputs['files'] if name not in inputs['bindings'] and name != 'index.html'}
    for mapping in mappings:
        asset = mapping['asset']
        require(asset['file'] not in files or files[asset['file']] == Path(asset['path']), 'prepared asset alias collision')
        files[asset['file']] = Path(asset['path'])
    return html, mappings, files


def write_project(inputs: dict, binding: dict, destination: Path) -> dict:
    """Copy into a new project; preserve every original and the current export pipeline."""
    verify_pins(inputs['pins'])
    result, package_pins = read_package(binding)
    html, mappings, files = mapped_files(inputs, result)
    destination.mkdir(mode=0o700)
    for name, source in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
        require(hash_file(target) == hash_file(source), f'long-form asset changed while copying: {name}')
    (destination / 'index.html').write_text(html)
    names = ['index.html', *files]
    record = {'schemaVersion': 1, 'status': 'prepared-awaiting-native-qc', 'inputs': inputs,
              'package': binding, 'mappings': mappings,
              'files': {name: hash_file(destination / name) for name in names},
              'originalPipelineModified': False, 'additionalPictureEncodes': 0}
    verify_pins({**inputs['pins'], **package_pins})
    write_new(destination / MANIFEST, record)
    return record


def check_project(project: Path) -> dict:
    """Refuse missing, altered, rehashed or source-divergent prepared projects."""
    record = bound_json(project / MANIFEST)
    require(record.get('schemaVersion') == 1 and record.get('status') == 'prepared-awaiting-native-qc',
            'unknown long-form preparation record')
    inputs = project_inputs(Path(record['inputs']['project']))
    require(inputs == record['inputs'], 'original long-form project changed after preparation')
    result, _pins = read_package(record['package'])
    html, mappings, files = mapped_files(inputs, result)
    require(mappings == record['mappings'], 'long-form source mappings changed')
    require(project_html(project) == html, 'long-form executable changed after preparation')
    expected = {'index.html': hash_file(project / 'index.html'), **{name: hash_file(file) for name, file in files.items()}}
    require(record['files'] == expected, 'long-form prepared inventory changed')
    current = source_state(project)
    require(set(current['files']) == {*expected, MANIFEST}, 'long-form prepared inventory is missing or has extra files')
    for name, sha in expected.items():
        require(hash_file(project / name) == sha, f'long-form prepared file changed: {name}')
    return record
