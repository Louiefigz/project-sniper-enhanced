"""Deterministic worker and Docker facts for mezzanine unit tests."""
from __future__ import annotations

import hashlib
import os

from headless.container_policy import DockerRuntime
from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from headless.qualification_mezzanine_policy import MEMORY_BYTES
from qualification_mezzanine_files import FileFact

SOURCE_FRAMES, SOURCE_RATE, TARGET_FRAMES = 20004, "24000/1001", 20024
SOURCE_VIDEO_DURATION = SOURCE_FRAMES * 1001 / 24000
SOURCE_SAMPLES, SOURCE_LAST_AUDIO_PTS = 40_048_080, 40_047_536
SOURCE_AUDIO_DURATION = SOURCE_SAMPLES / 48000
SOURCE_AUDIO_VIDEO_DELTA = SOURCE_AUDIO_DURATION - SOURCE_VIDEO_DURATION
TARGET_DURATION, TARGET_SAMPLES = TARGET_FRAMES / 24, TARGET_FRAMES * 2000
TARGET_TIMELINE_SAMPLES = ((TARGET_SAMPLES + 47) // 48) * 48
SILENT_TAIL_SAMPLES = TARGET_TIMELINE_SAMPLES - TARGET_SAMPLES


def runtime() -> DockerRuntime:
    """Return one approved-looking inert Docker runtime."""
    return DockerRuntime(
        "/usr/bin/docker", "/tmp/docker.sock", f"sha256:{'a' * 64}",
        "501:20", {"config": {"environment": [
            "PATH=/usr/bin:/bin", "LANG=C.UTF-8", "LC_ALL=C.UTF-8"]}})


def source_fact(path: str, changed: bool = False) -> FileFact:
    """Return stable or deliberately changed host byte authority."""
    return FileFact(path, ("d" if changed else "c") * 64,
                    MAX_EXTERNAL_MEDIA_BYTES + 1, 1, 2, 3, 4)


def _tool(name: str) -> dict:
    output = f"{name} exact version\n"
    return {"path": f"/usr/bin/{name}", "resolvedPath": f"/usr/bin/{name}",
            "sha256": "b" * 64, "sizeBytes": 123,
            "versionArgv": [f"/usr/bin/{name}", "-version"],
            "versionOutput": output,
            "versionOutputSha256": hashlib.sha256(output.encode()).hexdigest()}


def _source_probe(source_size: int) -> dict:
    return {"argv": ["/usr/bin/ffprobe", "-v", "error", "/input/source"],
            "facts": {"sizeBytes": source_size,
                        "durationSeconds": SOURCE_AUDIO_DURATION,
                        "width": 3840, "height": 2160,
                        "videoCodec": "h264", "audioCodec": "pcm_s16be",
                        "audioSampleRate": "48000", "audioChannels": 2,
                        "rate": SOURCE_RATE, "frames": SOURCE_FRAMES,
                        "timeBase": "1/24000", "firstPts": 0,
                        "lastPts": (SOURCE_FRAMES - 1) * 1001,
                        "frameStepPts": 1001, "zeroBasedEpoch": True,
                        "progressive": True,
                        "streamFieldOrder": "progressive",
                        "decodedProgressiveFrames": SOURCE_FRAMES,
                        "rotationDegrees": 0,
                        "sourceAudio": {
                            "codec": "pcm_s16be", "sampleRate": 48000,
                            "channels": 2, "timeBase": "1/48000",
                            "firstPts": 0, "lastPts": SOURCE_LAST_AUDIO_PTS,
                            "lastEndPts": SOURCE_SAMPLES,
                            "timelineSamplesPerChannel": SOURCE_SAMPLES,
                            "decodedSamplesPerChannel": SOURCE_SAMPLES,
                            "durationSeconds": SOURCE_AUDIO_DURATION,
                            "videoDurationDeltaSeconds":
                                SOURCE_AUDIO_VIDEO_DELTA,
                            "absoluteVideoDeltaWithinOneSourceFrame": True,
                            "contiguousFromZero": True,
                        },
                        "sha256": "c" * 64,
                        "postTranscodeSha256": "c" * 64}}


def _decisions() -> tuple[dict, dict, dict]:
    cadence = {
        "mode": "declared-palmier-integer-rate-approximation",
        "approvalPolicy": "sniper-palmier-project-rate-v1",
        "sourceRate": SOURCE_RATE, "targetRate": "24/1",
        "sourceFrames": SOURCE_FRAMES, "targetFrames": TARGET_FRAMES,
        "frameRounding": "nearest-target-frame-half-up",
        "sourceDurationSeconds": SOURCE_VIDEO_DURATION,
        "targetDurationSeconds": TARGET_DURATION,
        "durationDeltaSeconds": TARGET_DURATION - SOURCE_VIDEO_DURATION}
    geometry = (
        "scale=1920:1080:force_original_aspect_ratio=decrease:"
        "flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1,fps=fps=24/1:start_time=0:round=near,"
        f"trim=end_frame={TARGET_FRAMES},setpts=PTS-STARTPTS,format=yuv420p"
    )
    color = {"hdrDetected": False, "mode": "retain-bt709-sdr",
             "sourceTags": {"range": "tv", "space": "bt709",
                            "transfer": "bt709", "primaries": "bt709",
                            "pixelFormat": "yuv420p"},
             "targetTags": {"range": "tv", "space": "bt709",
                            "transfer": "bt709", "primaries": "bt709",
                            "pixelFormat": "yuv420p"},
             "filter": geometry}
    audio_filter = (
        "aresample=48000:async=0:first_pts=0,"
        f"atrim=end_sample={TARGET_SAMPLES},"
        f"apad=whole_len={TARGET_TIMELINE_SAMPLES},"
        f"atrim=end_sample={TARGET_TIMELINE_SAMPLES},"
        "asetpts=N/SR/TB")
    audio = {"mode": "full-program-with-bounded-silent-aac-tail",
             "sampleRate": 48000,
             "channels": 2,
             "programSamplesPerChannel": TARGET_SAMPLES,
             "targetTimelineSamplesPerChannel": TARGET_TIMELINE_SAMPLES,
             "presentationQuantumSamples": 48,
             "silentTailSamplesPerChannel": SILENT_TAIL_SAMPLES,
             "programDurationSeconds": TARGET_DURATION,
             "targetTimelineDurationSeconds":
                 TARGET_TIMELINE_SAMPLES / 48000,
             "filter": audio_filter}
    return cadence, color, audio


def _output_probe(output_size: int) -> dict:
    decoded_samples = TARGET_TIMELINE_SAMPLES + 608
    output_argv = [
        "/usr/bin/ffprobe", "-v", "error", "-count_frames",
        "-count_packets", "-show_streams", "-show_format", "-show_frames",
        "-show_entries",
        "stream:format:frame=media_type,pts,pkt_pts,best_effort_timestamp,"
        "duration,pkt_duration,nb_samples,interlaced_frame,top_field_first",
        "-of", "json", "/output/qualified.mp4",
    ]
    output = {"sizeBytes": output_size,
              "durationSeconds": TARGET_TIMELINE_SAMPLES / 48000,
              "video": {"codec": "h264", "width": 1920, "height": 1080,
                        "profile": "High", "level": 42,
                        "pixelFormat": "yuv420p", "rate": "24/1",
                        "sampleAspectRatio": "1:1", "timeBase": "1/24",
                        "startPts": 0, "durationFrames": TARGET_FRAMES,
                        "durationSeconds": TARGET_DURATION,
                        "frames": TARGET_FRAMES, "colorRange": "tv",
                        "firstPts": 0, "lastPts": TARGET_FRAMES - 1,
                        "frameStepPts": 1, "zeroBasedEpoch": True,
                        "progressive": True, "rotationDegrees": 0,
                        "colorSpace": "bt709", "colorTransfer": "bt709",
                        "colorPrimaries": "bt709"},
              "audio": {"codec": "aac", "sampleRate": 48000, "channels": 2,
                        "timeBase": "1/48000", "startPts": 0,
                        "programSamplesPerChannel": TARGET_SAMPLES,
                        "timelineSamplesPerChannel": TARGET_TIMELINE_SAMPLES,
                        "timelineDurationSeconds":
                            TARGET_TIMELINE_SAMPLES / 48000,
                        "decodedSamplesPerChannel": decoded_samples,
                        "decodedDurationSeconds": decoded_samples / 48000,
                        "silentTailSamplesPerChannel": SILENT_TAIL_SAMPLES,
                        "codecPaddingSamplesPerChannel": 608,
                        "fullProgramCoverage": True}}
    return {"argv": output_argv,
            "audioDecodeArgv": output_argv.copy(), "facts": output}


def worker(source_size: int, output_size: int) -> dict:
    """Build exact trusted-worker evidence for one 24000/1001 source."""
    cadence, color, audio = _decisions()
    tools = {"ffmpeg": _tool("ffmpeg"), "ffprobe": _tool("ffprobe")}
    return {"schemaVersion": 1, "ok": True, "tools": tools,
            "sourceProbe": _source_probe(source_size),
            "cadenceDecision": cadence,
            "colorDecision": color, "audioDecision": audio,
            "transcode": {"argv": ["/usr/bin/ffmpeg", "-vf",
                                   color["filter"], "-af", audio["filter"],
                                   "-vsync", "cfr", "-n",
                                   "/output/qualified.mp4"],
                          "maxVideoBitrateBps": 40000000},
            "outputProbe": _output_probe(output_size)}


def envelope(source_size: int, output_size: int) -> dict:
    """Wrap worker facts in successful isolated-runtime evidence."""
    return {"image": {"imageId": f"sha256:{'a' * 64}",
                      "architecture": "arm64", "os": "linux"},
            "isolation": {"networkMode": "none", "readonlyRoot": True},
            "removal": {"canonicalAbsenceProved": True},
            "worker": worker(source_size, output_size)}


def inspect_document(
    docker_runtime: DockerRuntime,
    source: str,
    output: str,
    command: list[str],
) -> dict:
    """Build one exact Docker inspect response."""
    image_index = command.index(docker_runtime.image_id)
    environment = ["PATH=/usr/bin:/bin", "LANG=C.UTF-8", "LC_ALL=C.UTF-8",
                   "TZ=UTC", "TMPDIR=/scratch"]
    host = {"NetworkMode": "none", "ReadonlyRootfs": True,
            "Privileged": False, "CapDrop": ["ALL"], "CapAdd": None,
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": MEMORY_BYTES, "MemorySwap": MEMORY_BYTES,
            "NanoCpus": 4_000_000_000, "PidsLimit": 128, "Init": True,
            "LogConfig": {"Type": "none"},
            "Tmpfs": {"/scratch": "rw,nosuid,nodev,noexec,"
                      "size=256m,uid=501,gid=20,mode=0700"}}
    return {"Id": "f" * 64, "Image": docker_runtime.image_id,
            "Config": {"User": docker_runtime.user_id,
                       "Entrypoint": ["/usr/bin/node"],
                       "Cmd": command[image_index + 1:], "Env": environment},
            "HostConfig": host, "State": {"Running": True},
            "Mounts": [{"Source": os.path.realpath(source),
                        "Destination": "/input/source", "RW": False},
                       {"Source": os.path.realpath(output),
                        "Destination": "/output", "RW": True}],
            "NetworkSettings": {"Networks": {"none": {}}}}
