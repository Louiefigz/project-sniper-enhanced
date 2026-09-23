"""Explicit owned real-media fixture for the native long exporter; no provider calls."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, write_new
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import REPO, digest, install_runtime


def worker(request: dict) -> None:
    """Generate only bounded test media underneath the same production owner."""
    project, tools = Path(request['project']), request['tools']
    duration = str(request['canvas']['totalFrames'] // 30)
    subprocess.run([tools['ffmpeg'], '-nostdin', '-v', 'error', '-n', '-f', 'lavfi',
        '-i', 'color=c=0x31546b:s=320x180:r=30', '-t', duration, '-an', '-c:v', 'libx264',
        '-crf', '15', '-pix_fmt', 'yuv420p', str(project / 'assets/picture.mp4')], check=True, timeout=60)
    audio_input = ['-ss', '8', '-i', request['audio']]
    if int(duration) > 180:
        audio_input = ['-f', 'lavfi', '-i', 'anoisesrc=color=pink:r=48000:amplitude=0.1:seed=41']
    subprocess.run([tools['ffmpeg'], '-nostdin', '-v', 'error', '-n', *audio_input,
        '-t', duration, '-ar', '48000', '-ac', '2', '-c:a', 'pcm_f32le',
        '-af', f"asetpts=N/SR/TB,atrim=end_sample={int(duration)*48000}",
        str(project / 'assets/dialogue.wav')], check=True, timeout=60)
    write_new(Path(request['output']) / 'fixture.json', {'status': 'fixture-generated', 'productionDelivery': False,
        'audio': 'deterministic broadband stress signal' if int(duration)>180 else 'explicit source excerpt'})


def author(project: Path, gsap: Path, canvas: dict) -> None:
    """Use a flat native cut without nested timed media or layout mutation."""
    (project / 'assets').mkdir(parents=True)
    shutil.copyfile(gsap, project / 'assets/gsap.min.js')
    html = '''<!doctype html><html><head><meta charset="utf-8"><title>Long export technical fixture</title>
<script src="assets/gsap.min.js"></script><style>
body{margin:0}#root{position:relative;width:320px;height:180px;background:#14232f;overflow:hidden}
video{position:absolute;inset:0;width:320px;height:180px;object-fit:cover}
#second{left:80px;width:240px}
</style></head><body><div id="root" data-composition-id="long-test" data-width="320"
data-height="180" data-duration="4" data-fps="30">
<video id="first" class="clip" src="assets/picture.mp4" data-start="0" data-duration="2"
data-media-start="0" data-track-index="0" muted playsinline></video>
<video id="second" class="clip" src="assets/picture.mp4" data-start="2" data-duration="2"
data-media-start="2" data-track-index="1" muted playsinline></video>
<audio id="dialogue" src="assets/dialogue.wav" data-start="0" data-duration="4" data-track-index="10"></audio>
</div><script>const tl=gsap.timeline({paused:true});window.__timelines['long-test']=tl;</script></body></html>'''
    seconds, half = canvas['totalFrames'] // 30, canvas['totalFrames'] // 60
    html = html.replace('320', str(canvas['width'])).replace('180', str(canvas['height']))
    html = html.replace('left:80px;width:240px', f"left:{canvas['width']//4}px;width:{canvas['width']*3//4}px")
    html = html.replace('data-duration="4"', f'data-duration="{seconds}"')
    html = html.replace('data-duration="2"', f'data-duration="{half}"')
    html = html.replace('data-start="2"', f'data-start="{half}"').replace('data-media-start="2"', f'data-media-start="{half}"')
    (project / 'index.html').write_text(html)
    write_new(project / 'LONG-PROJECT.json', {'schemaVersion': 1,
        'canvas': canvas,
        'audio': {'file': 'assets/dialogue.wav'}, 'scenes': [
            {'startFrame': 0, 'endFrame': canvas['totalFrames']//2, 'mediaIds': ['first']},
            {'startFrame': canvas['totalFrames']//2, 'endFrame': canvas['totalFrames'], 'mediaIds': ['second']}]})


def prepare(root: Path, audio: Path, gsap: Path, canvas: dict) -> bool:
    """Require current source pins, shared host gates and verified child cleanup."""
    root.mkdir()
    project, output = root / 'project', root / 'preparation'
    author(project, gsap, canvas)
    output.mkdir()
    tools, environment = local_environment()
    runtime = install_runtime()
    cli = runtime / 'dist/cli.js'
    sandbox = REPO / 'scripts/producer/studio/native_localhost_only.sb'
    request = {'project': str(project), 'output': str(output), 'audio': str(audio), 'tools': tools, 'canvas': canvas}
    file = output / 'request.json'
    write_new(file, request)
    pins = {str(path): digest(path) for path in (file, audio, Path(__file__).resolve(),
        project / 'index.html', project / 'assets/gsap.min.js', project / 'LONG-PROJECT.json')}
    settings = NativeRunConfig(project, output, cli,
        ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(Path(__file__).resolve()),
         'worker', str(file)], environment, {'output': str(output / 'fixture.json'),
         'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)}, additional_pins=pins,
         success_status='long-test-fixture-complete', deadline=1200, capacity_wait_seconds=600)
    return NativeRun('fixture', settings).execute()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'worker'))
    parser.add_argument('path', type=Path)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--gsap', type=Path)
    parser.add_argument('--seconds', type=int, default=4)
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--height', type=int, default=180)
    args = parser.parse_args()
    if args.operation == 'worker':
        worker(bound_json(args.path))
    else:
        if not 2 <= args.seconds <= 900 or args.seconds % 2:
            raise ValueError('Stress fixture duration must be an even integer through 900 seconds')
        canvas = {'width': args.width, 'height': args.height, 'frameRate': '30/1', 'totalFrames': args.seconds*30}
        raise SystemExit(0 if prepare(args.path.absolute(), args.audio.resolve(strict=True),
                                     args.gsap.resolve(strict=True), canvas) else 1)
