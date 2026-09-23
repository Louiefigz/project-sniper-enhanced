"""Prepare immutable checked MP4 review and independent editable Studio packages."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from cut_preview_io import bound_json, real_directory, write_new
from studio.native_review_contract import read_manifest, relative_file
from studio.native_review_html import adapt_html, canvas_clock, frame_points
from studio.native_review_media import STATUS, worker
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import digest
from studio.native_short_picture_reuse import copy_picture
from studio.native_stage_evidence import require, verify_pins

HERE = Path(__file__).resolve().parent
RECEIPT = 'NATIVE-REVIEW-BUNDLE.json'
PLAYER = HERE.parents[2] / 'templates/clip-review/playback.mjs'


def clone_composition(row: object, output: Path) -> dict:
    """Copy only admitted files; never modify or reinterpret the production manifest."""
    studio = output / 'studio' / row.identity
    studio.mkdir(parents=True)
    for name, sha in row.files.items():
        source = relative_file(row.project, name); target = studio / name
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_picture(source, target, sha)
    config = bound_json(studio / 'hyperframes.json') if 'hyperframes.json' in row.files else {}
    config['media'] = {**config.get('media', {}), 'autoProxy': False}
    (studio / 'hyperframes.json').write_text(json.dumps(config, indent=2) + '\n')
    before = relative_file(studio, row.entry).read_text()
    adapted, proof = adapt_html(before, row.plan['canvas'], row.native_long)
    root = output / 'preparation' / row.identity; root.mkdir(parents=True)
    (root / 'index.before.html').write_text(before)
    (root / 'index.adapted.html').write_text(adapted)
    timeline, _duration = canvas_clock(row.plan['canvas'])
    return {'id': row.identity, 'title': row.title, 'studio': str(studio), 'root': str(root),
        'entry': row.entry, 'project': str(row.project), 'originalFiles': row.files,
        'video': str(row.video), 'videoSha256': row.video_sha256,
        'samples': timeline.sample_at_frame(row.plan['canvas']['totalFrames']),
        'frames': frame_points(row.plan), 'proof': proof,
        'htmlBeforeSha256': digest(studio / row.entry), 'htmlAfterSha256': digest(root / 'index.adapted.html'),
        'forkFiles': {name: digest(studio / name) for name in {*row.files, 'hyperframes.json'}}}


def implementation_pins() -> dict[str, str]:
    """Pin this package and the existing copy, clock, media and HTML utilities."""
    files = [PLAYER, *HERE.glob('native_review_*.py')]
    files += [HERE / name for name in ('native_media_visibility.py', 'native_short_picture_reuse.py',
              'native_stage_evidence.py', 'native_short_delivery.py', 'native_short_resume.py', 'native_long_contract.py')]
    files += list((HERE.parent / 'audio').glob('*.py'))
    files += [HERE.parent / 'cut_preview_io.py', HERE.parent / 'edit/exact_timing.py', Path(sys.executable).resolve()]
    return {str(file): digest(file) for file in files}


def prepare(manifest: Path, output: Path) -> tuple[dict, Path]:
    """Validate all entries before creating a fresh bundle or acquiring heavy work."""
    manifest = manifest.resolve(strict=True); output = output.absolute()
    real_directory(output.parent)
    require(not output.exists() and not output.is_symlink(), 'review bundle needs a fresh output directory')
    manifest_sha = digest(manifest); rows = read_manifest(manifest)
    for row in rows:
        require(all(output != root and not output.is_relative_to(root) and not root.is_relative_to(output)
                    for root in (row.project, row.export)), 'review output overlaps original work')
    tools, environment = local_environment()
    pins = {str(manifest): manifest_sha, **implementation_pins(), **{str(Path(value)): digest(Path(value)) for value in tools.values()}}
    for row in rows:
        require(all(file not in pins or pins[file] == sha for file, sha in row.pins.items()), 'conflicting review input hashes')
        pins.update(row.pins)
    verify_pins(pins)
    output.mkdir(mode=0o700)
    compositions = [clone_composition(row, output) for row in rows]
    for row in compositions:
        pins.update({str(Path(row['studio']) / name): sha for name, sha in row['forkFiles'].items()})
        pins.update({str(Path(row['root']) / name): digest(Path(row['root']) / name)
                     for name in ('index.before.html', 'index.adapted.html')})
    request = {'schemaVersion': 1, 'root': str(output), 'runtime': str(rows[0].runtime), 'tools': tools,
               'pins': pins, 'compositions': compositions}
    project = output / 'owner-input'; project.mkdir()
    file = project / 'request.json'; write_new(file, request)
    verify_pins(pins)
    return request, file


def supervise(request: dict, file: Path) -> NativeRun:
    """Own sequential AAC/checkpoint work under the existing resource limits."""
    _tools, environment = local_environment()
    require(_tools == request['tools'], 'review media tools changed')
    root = Path(request['root']); cli = Path(request['runtime']) / 'dist/cli.js'
    sandbox = HERE / 'native_localhost_only.sb'
    settings = NativeRunConfig(file.parent, root, cli,
        ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(Path(__file__).resolve()), '--worker', str(file)],
        environment, {'output': str(root / 'media-preparation.json'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
        additional_pins={**request['pins'], str(file): digest(file)}, deadline=600, success_status=STATUS)
    owner = NativeRun('native-review', settings)
    require(owner.execute(), 'review preparation owner failed; preserve the attempt')
    return owner


def publish_composition(row: dict, media: dict, output: Path) -> dict:
    """Publish copied AAC/HTML in its new fork and exact MP4 on the local review page."""
    studio, root = Path(row['studio']), Path(row['root'])
    require(media['id'] == row['id'] and media['videoSha256'] == row['videoSha256'], 'review media identity differs')
    audio = media['audio']
    require(audio.get('audioPacketsIdentical') is True and audio.get('additionalAudioEncodes') == 0
            and audio.get('additionalVideoEncodes') == 0 and audio['path'] == str(root / 'studio-dialogue.m4a'), 'unqualified review AAC')
    for record in [audio, *media['frames']]:
        require(Path(record['path']).is_relative_to(root) and digest(Path(record['path'])) == record['sha256'], 'prepared review artifact changed')
    require([{key: frame[key] for key in ('frame', 'seconds')} for frame in media['frames']] == row['frames'], 'review frame schedule changed')
    verify_pins({str(studio / name): sha for name, sha in row['forkFiles'].items()})
    audio_target = studio / 'assets/studio-dialogue.m4a'
    copy_picture(Path(audio['path']), audio_target, audio['sha256'])
    require(digest(studio / row['entry']) == row['htmlBeforeSha256'], 'editable Studio HTML changed before publication')
    adapted = root / 'index.adapted.html'
    require(digest(adapted) == row['htmlAfterSha256'], 'adapted Studio HTML changed')
    (studio / row['entry']).write_bytes(adapted.read_bytes())
    require(digest(studio / row['entry']) == row['htmlAfterSha256'], 'Studio HTML publication differs')
    video = output / 'media' / f'{row["id"]}.mp4'
    copy_picture(Path(row['video']), video, row['videoSha256'])
    fork = {**row['forkFiles'], row['entry']: row['htmlAfterSha256'], 'assets/studio-dialogue.m4a': audio['sha256']}
    return {**row, 'audio': audio, 'frames': media['frames'], 'forkFiles': fork, 'localVideo': str(video),
            'localVideoSha256': row['videoSha256'], 'browserPlaybackVerified': False, 'humanListeningApproved': False}


def local_page(rows: list[dict]) -> str:
    """Embed the pinned shared player so recovery also works on local file pages."""
    source = PLAYER.read_text()
    require(source.count('export class SelectionPlayback') == 1, 'shared review player contract changed')
    player = source.replace('export class SelectionPlayback', 'class SelectionPlayback', 1)
    require('</script' not in player.lower(), 'shared player cannot be embedded safely')
    cards = ''.join(f'<section><h2>{escape(row["title"])}</h2><video controls preload="metadata" playsinline '
                    f'data-duration="{row["samples"] / 48000}" src="media/{row["id"]}.mp4"></video>'
                    '<p><button data-action="play">Play / replay</button> <button data-action="resume">Resume</button> '
                    '<button data-action="reload">Reload video</button></p><p role="status">Ready</p></section>' for row in rows)
    controls = """document.querySelectorAll('section').forEach(section=>{
const media=section.querySelector('video'),status=section.querySelector('[role="status"]');
const playback=new SelectionPlayback(media,event=>{status.textContent=event.message||event.state;});
section.querySelector('[data-action="play"]').addEventListener('click',()=>
  playback.start([{start:0,end:Number(media.dataset.duration)}],media.getAttribute('src')));
section.querySelector('[data-action="resume"]').addEventListener('click',()=>playback.resume());
section.querySelector('[data-action="reload"]').addEventListener('click',()=>playback.reload());
});"""
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Video review</title><style>'
            'body{font:18px system-ui;background:#171717;color:#fff;margin:32px}section{margin-bottom:48px}'
            'video{max-width:100%;max-height:80vh}button{font:inherit}</style></head><body><h1>Video review</h1>'
            + cards + '<script>' + player + '\n' + controls + '</script></body></html>')


def publish(request: dict, owner: NativeRun) -> dict:
    """Complete the bundle only after verified owned cleanup and immutable input checks."""
    require(owner.result.get('status') == STATUS and owner.result.get('exitCode') == 0
            and owner.result.get('cleanup', {}).get('verified') is True
            and owner.result.get('leaseCleanupVerified') is True, 'review owner cleanup is incomplete')
    verify_pins(request['pins'])
    output = Path(request['root']); media = bound_json(output / 'media-preparation.json')
    require(media.get('status') == STATUS and len(media['compositions']) == len(request['compositions']), 'incomplete review media')
    (output / 'media').mkdir()
    rows = [publish_composition(row, prepared, output)
            for row, prepared in zip(request['compositions'], media['compositions'], strict=True)]
    for row in rows:
        verify_pins({str(Path(row['project']) / name): sha for name, sha in row['originalFiles'].items()})
    page = output / 'index.html'; page.write_text(local_page(rows))
    result = {'schemaVersion': 1, 'status': 'native-review-bundle-prepared', 'root': str(output), 'runtime': request['runtime'],
        'localReview': str(page), 'localReviewSha256': digest(page), 'compositions': rows,
        'playerSource': str(PLAYER), 'playerSourceSha256': request['pins'][str(PLAYER)],
        'owner': str(owner.path), 'ownerSha256': digest(owner.path),
        'request': str(output / 'owner-input/request.json'), 'requestSha256': digest(output / 'owner-input/request.json'),
        'browserPlaybackVerified': False, 'humanListeningApproved': False,
        'limitation': 'Source/cut changes require rebuilding the final AAC; Studio edits require new export and verification.'}
    write_new(output / RECEIPT, result)
    return result


def studio_state(row: dict) -> dict:
    """Describe editable divergence without treating it as a new checked export."""
    studio = Path(row['studio']); changed = []
    for name, sha in row['forkFiles'].items():
        file = studio / name
        if not file.is_file() or file.is_symlink() or digest(file) != sha:
            changed.append(name)
    visible = {str(file.relative_to(studio)) for file in studio.rglob('*') if file.is_file()
               and not any(part.startswith('.') or part == 'node_modules' for part in file.relative_to(studio).parts)}
    added = sorted(visible - row['forkFiles'].keys())
    return {'status': 'edited-since-preparation' if changed or added else 'prepared-files-unchanged',
            'changedOrMissingFiles': sorted(changed), 'addedFiles': added,
            'exportConsistencyVerified': False, 'newExportRequiredForEdits': bool(changed or added)}


def read_bundle(directory: Path) -> dict:
    """Validate publication evidence before opening a selected editable project."""
    directory = directory.resolve(strict=True); real_directory(directory)
    record = bound_json(directory / RECEIPT)
    require(record.get('status') == 'native-review-bundle-prepared' and record.get('root') == str(directory), 'review bundle is incomplete or moved')
    owner = bound_json(Path(record['owner']), record['ownerSha256'])
    request = bound_json(Path(record['request']), record['requestSha256'])
    require(owner.get('status') == STATUS and owner.get('exitCode') == 0 and not owner.get('abortReason')
            and owner.get('cleanup', {}).get('verified') is True and owner.get('leaseCleanupVerified') is True,
            'review publication owner did not complete')
    before = owner.get('additionalFilePinsBefore', {})
    require(before == owner.get('additionalFilePinsAfter') and before.get(record['request']) == record['requestSha256']
            and all(before.get(file) == sha for file, sha in request['pins'].items()), 'review owner did not bind its full request')
    require(owner.get('output') == str(directory / 'media-preparation.json')
            and request['root'] == str(directory) and record['runtime'] == request['runtime'], 'review publication origin differs')
    require(record['localReview'] == str(directory / 'index.html')
            and digest(directory / 'index.html') == record['localReviewSha256'], 'local review page changed')
    require([row['id'] for row in record['compositions']] == [row['id'] for row in request['compositions']], 'review composition list changed')
    for row in record['compositions']:
        studio = directory / 'studio' / row['id']
        require(row['studio'] == str(studio) and studio.resolve(strict=True) == studio, 'review Studio path escaped bundle')
        video = directory / 'media' / f'{row["id"]}.mp4'
        require(row['localVideo'] == str(video) and digest(video) == row['localVideoSha256'], 'local review MP4 changed')
        require(bound_json(studio / 'hyperframes.json').get('media', {}).get('autoProxy') is False, 'Studio automatic proxies were enabled')
        row['localVideoStatus'] = 'checked-bytes-unchanged'
        row['studioState'] = studio_state(row)
    return record


def open_bundle(directory: Path, identity: str) -> dict:
    """Open actual managed Studio and report editable state separately from MP4 proof."""
    from studio.managed_preview import open_preview
    from studio.native_runtime import install_runtime
    bundle = read_bundle(directory)
    rows = [row for row in bundle['compositions'] if row['id'] == identity]
    require(len(rows) == 1, 'unknown review composition')
    require(str(install_runtime()) == bundle['runtime'], 'current Studio runtime differs from the prepared bundle')
    preview = open_preview(rows[0]['studio']).to_json()
    return {**preview, 'surface': 'managed-hyperframes-studio', 'studioState': rows[0]['studioState'],
            'localVideoStatus': rows[0]['localVideoStatus'], 'browserPlaybackVerified': False}


def main() -> None:
    """Prepare a bundle; open its chosen Studio project explicitly through managed preview."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    build = sub.add_parser('prepare'); build.add_argument('manifest', type=Path); build.add_argument('output', type=Path)
    show = sub.add_parser('open'); show.add_argument('bundle', type=Path); show.add_argument('composition')
    args = parser.parse_args()
    if args.action == 'prepare':
        request, file = prepare(args.manifest, args.output); print(json.dumps(publish(request, supervise(request, file))))
    else:
        print(json.dumps(open_bundle(args.bundle, args.composition)))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]))
    else:
        main()
