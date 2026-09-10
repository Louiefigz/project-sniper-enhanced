"""Docker command and attestation policy for untrusted media decode."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from headless.container_policy import DockerRuntime, command, docker_env
from headless.external_media_probe_document import validate_probe_document
PROBE_MEMORY_MIB, PROBE_MEMORY_BYTES = 768, 768 * 1024 ** 2  # 4K HEVC bound.
# Probe decode CPUs (2026-09-07): the sealed validation decode of the real 10.28 GB / 834 s long-form source
# took 1068 s inside a one-CPU container with `-threads 1` (89 % of its 20-minute ceiling). Measured on the host
# for a 60 s excerpt of that source: 1 thread 57.2 s, 4 threads 25.6 s (2.2x). Four CPUs match the sealed live
# render policy (container_live_policy) and keep the same read-only, networkless, nonroot, no-new-privileges wall.
PROBE_CPUS = 4
NODE_PROBE = r"""
const cp=require('node:child_process'),fs=require('node:fs');
const input='/input/media',output='/scratch/result.json';
const limits={bytes:Number(process.argv[1]),width:Number(process.argv[2]),
 height:Number(process.argv[3]),frames:Number(process.argv[4]),
 duration:Number(process.argv[5]),streams:Number(process.argv[6]),
 decode:Number(process.argv[7])};
function publish(value){const temp=output+'.tmp';fs.writeFileSync(temp,
 JSON.stringify(value)+'\n',{flag:'wx',mode:0o600});fs.renameSync(temp,output);}
function fail(code,message){publish(
 {schemaVersion:1,ok:false,code,message});setTimeout(()=>{},30000);}
function pass(facts){publish(
 {schemaVersion:1,ok:true,decoded:true,facts});setTimeout(()=>{},30000);}
function run(cmd,args,timeout){const row=cp.spawnSync(cmd,args,
 {encoding:'utf8',timeout,maxBuffer:1048576,env:{PATH:'/usr/bin:/bin',
 LANG:'C.UTF-8',LC_ALL:'C.UTF-8',TZ:'UTC'}});
 if(row.error)throw new Error(row.error.code||row.error.message);
 if(row.status!==0||String(row.stderr||'').trim()){const term=row.signal?
  `DECODER_SIGNAL_${row.signal}`:row.status===0?'DECODER_STDERR':
  Number.isInteger(row.status)?`DECODER_EXIT_${row.status}`:
  'DECODER_TERMINATED';throw new Error((row.stderr||term).slice(-400));}
 return row.stdout;}
function special(){
 const stat=fs.statSync(input);if(stat.size<=0||stat.size>limits.bytes)
  throw new Error('SIZE_LIMIT');
 const fd=fs.openSync(input,'r'),head=Buffer.alloc(Math.min(65536,stat.size));
 fs.readSync(fd,head,0,head.length,0);fs.closeSync(fd);
 const magic=head.subarray(0,4).toString('binary');
 if(magic==='\x00\x01\x00\x00'||magic==='OTTO'||magic==='true'){
  const tables=head.readUInt16BE(4);
  if(tables<1||tables>128||12+tables*16>head.length)throw new Error('FONT_TABLE_LIMIT');
  for(let i=0;i<tables;i++){const at=12+i*16,off=head.readUInt32BE(at+8),
   len=head.readUInt32BE(at+12);if(off+len>stat.size)throw new Error('FONT_TABLE_RANGE');}
  return {mediaKind:'font',durationSeconds:0,sizeBytes:stat.size,width:0,height:0,
   videoStreams:0,audioStreams:0,streamCount:1,declaredFrames:0};
 }
 const prefix=head.subarray(0,1024).toString('utf8').trimStart().toLowerCase();
 if(prefix.startsWith('<svg')||prefix.startsWith('<?xml')){
  if(stat.size>16777216)throw new Error('SVG_SIZE_LIMIT');
  const text=fs.readFileSync(input,'utf8'),lower=text.toLowerCase();
  const remote=lower.replaceAll('http://www.w3.org/2000/svg','')
   .replaceAll('http://www.w3.org/1999/xlink','');
  if(!lower.includes('<svg')||/<!doctype|<!entity|<script|javascript:|https?:\/\/|onload\s*=|onerror\s*=|<foreignobject/.test(remote))
   throw new Error('SVG_ACTIVE_CONTENT');
  const svg=(text.match(/<svg\b[^>]*>/i)||[])[0]||'';
  const view=(svg.match(/\bviewBox\s*=\s*["']\s*[\d.+-]+\s+[\d.+-]+\s+([\d.]+)\s+([\d.]+)\s*["']/i)||[]);
  const wm=(svg.match(/\bwidth\s*=\s*["']([\d.]+)/i)||[]),hm=(svg.match(/\bheight\s*=\s*["']([\d.]+)/i)||[]);
  const width=Number(wm[1]||view[1]||0),height=Number(hm[1]||view[2]||0);
  if(!(width>0&&height>0)||width>limits.width||height>limits.height)
   throw new Error('DIMENSION_LIMIT');
  return {mediaKind:'svg',durationSeconds:0,sizeBytes:stat.size,width,height,
   videoStreams:1,audioStreams:0,streamCount:1,declaredFrames:1};
 }return null;
}
try{
 const parsed=special();if(parsed){pass(parsed);}else{
 const raw=run('/usr/bin/ffprobe',['-v','error','-show_streams','-show_format',
  '-of','json',input],10000),probe=JSON.parse(raw),streams=probe.streams||[];
 if(streams.length<1||streams.length>limits.streams)throw new Error('STREAM_LIMIT');
 const format=probe.format||{},duration=Number(format.duration||0),
  size=Number(format.size||0);
 if(!Number.isFinite(size)||size<=0||size>limits.bytes)throw new Error('SIZE_LIMIT');
 let decodedFrames=0,width=0,height=0,video=0,audio=0;
 for(const stream of streams){
  if(stream.codec_type==='video'){video++;width=Math.max(width,Number(stream.width||0));
   height=Math.max(height,Number(stream.height||0));
   let frames=Number(stream.nb_frames||0);
   if(!frames){const p=String(stream.avg_frame_rate||'0/1').split('/').map(Number);
    frames=p[1]?Math.ceil(duration*p[0]/p[1]):0;}decodedFrames+=frames;}
  if(stream.codec_type==='audio')audio++;
 }
 if(width>limits.width||height>limits.height)throw new Error('DIMENSION_LIMIT');
 const still=video>0&&audio===0&&(!Number.isFinite(duration)||duration<=0);
 if((!still&&(!Number.isFinite(duration)||duration<=0||duration>limits.duration)))
  throw new Error('DURATION_LIMIT');
 if(still)decodedFrames=Math.max(1,decodedFrames);
 if(decodedFrames>limits.frames)throw new Error('FRAME_LIMIT');
 const decodeMs=limits.decode*1000;
 run('/usr/bin/ffmpeg',['-nostdin','-v','error','-xerror','-threads','4','-i',
  input,'-map','0:v?','-map','0:a?','-vsync','vfr','-f','null','-'],decodeMs);
 pass({mediaKind:still?'still-image':'timed-media',
  durationSeconds:still?0:duration,sizeBytes:size,width,height,videoStreams:video,
  audioStreams:audio,streamCount:streams.length,declaredFrames:decodedFrames});
 }
}catch(error){fail(error.message||'DECODE_REJECTED',String(error).slice(-400));}
"""

@dataclass(frozen=True)
class MediaProbeLimits:
    """Hard decode and metadata ceilings enforced inside the container.

    ``max_bytes`` follows the admission snapshot bound (16 GiB since
    2026-09-07, the real 9.58 GiB long-form source class); every other
    ceiling is unchanged and still fails closed inside the sealed probe.
    """
    max_bytes: int = 16 * 1024 ** 3
    max_width: int = 8192
    max_height: int = 8192
    max_frames: int = 2_000_000
    max_duration_seconds: int = 6 * 60 * 60
    max_streams: int = 32
    max_decode_seconds: int = 20 * 60
@dataclass(frozen=True)
class _ProbeLaunch:
    config_dir: str
    name: str
    snapshot: str
    limits: MediaProbeLimits

def _probe_launch(arguments: tuple[object, ...]) -> _ProbeLaunch:
    if len(arguments) != 4:
        raise TypeError("container_command requires four launch arguments")
    config_dir, name, snapshot, limits = arguments
    if not isinstance(config_dir, str) or not isinstance(name, str) \
            or not isinstance(snapshot, str) \
            or not isinstance(limits, MediaProbeLimits):
        raise TypeError("external media probe launch arguments are malformed")
    return _ProbeLaunch(config_dir, name, snapshot, limits)

def container_command(
    runtime: DockerRuntime,
    *arguments: object,
) -> list[str]:
    """Build one secret-free, read-only, nonroot, networkless probe command."""
    launch = _probe_launch(arguments)
    name, snapshot, limits = launch.name, launch.snapshot, launch.limits
    if (type(limits.max_decode_seconds) is not int
            or not 90 <= limits.max_decode_seconds <= 3600):
        raise RuntimeError(
            "external media decode timeout must be 90..3600 seconds")
    if "," in snapshot:
        raise RuntimeError("external media snapshot path cannot contain commas")
    mount = f"type=bind,src={snapshot},dst=/input/media,readonly"
    result_dir = os.path.realpath(os.path.join(launch.config_dir, "result"))
    if "," in result_dir:
        raise RuntimeError("external media result path cannot contain commas")
    result_mount = f"type=bind,src={result_dir},dst=/scratch"
    result = command(
        runtime, "run", "--detach", "--pull", "never", "--name", name,
        "--platform", "linux/arm64", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--user", runtime.user_id, "--pids-limit", "64",
        "--memory", f"{PROBE_MEMORY_MIB}m", "--memory-swap",
        f"{PROBE_MEMORY_MIB}m",
        "--cpus", str(PROBE_CPUS), "--init",
        "--stop-timeout", "5", "--log-driver", "none",
        "--ulimit", "nofile=256:256", "--hostname", "sniper-media-probe",
        "--mount", mount, "--mount", result_mount,
        "--entrypoint", "/usr/bin/node",
    )
    for key, value in {
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
    }.items():
        result.extend(("--env", f"{key}={value}"))
    result.extend((runtime.image_id, "-e", NODE_PROBE,
                   str(limits.max_bytes), str(limits.max_width),
                   str(limits.max_height), str(limits.max_frames),
                   str(limits.max_duration_seconds), str(limits.max_streams),
                   str(limits.max_decode_seconds)))
    return result

def _inspect(runtime: DockerRuntime, config_dir: str, name: str) -> dict:
    proc = subprocess.run(
        command(runtime, "container", "inspect", name, "--format", "{{json .}}"),
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=docker_env(config_dir), timeout=15, check=False)
    if proc.returncode != 0:
        raise RuntimeError("could not inspect external-media probe container")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("media-probe inspect returned invalid JSON") from exc

@dataclass(frozen=True)
class _ProbeAttestation:
    config_dir: str
    name: str
    snapshot: str
    expected_command: list[str]

@dataclass(frozen=True)
class _ObservedContainer:
    actual: dict
    config: dict
    host: dict
    state: dict
    source: str
    result_dir: str
    expected_cmd: list[str]
    networks: dict
    environment: dict[str, str]
    expected_environment: dict[str, str]

def _probe_attestation(arguments: tuple[object, ...]) -> _ProbeAttestation:
    if len(arguments) != 4:
        raise TypeError("attest_probe_container requires four arguments")
    config_dir, name, snapshot, expected = arguments
    valid = (
        isinstance(config_dir, str)
        and isinstance(name, str)
        and isinstance(snapshot, str)
        and isinstance(expected, list)
    )
    if not valid:
        raise TypeError("external media probe attestation is malformed")
    return _ProbeAttestation(config_dir, name, snapshot, expected)

def _observed_container(
    runtime: DockerRuntime,
    request: _ProbeAttestation,
) -> _ObservedContainer:
    actual = _inspect(runtime, request.config_dir, request.name)
    config = actual.get("Config") or {}
    host = actual.get("HostConfig") or {}
    image_index = request.expected_command.index(runtime.image_id)
    pairs = [
        row.split("=", 1) for row in config.get("Env") or [] if "=" in row]
    expected_environment = dict(
        row.split("=", 1)
        for row in runtime.approval["config"]["environment"])
    expected_environment.update({
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"})
    return _ObservedContainer(
        actual, config, host, actual.get("State") or {},
        os.path.realpath(request.snapshot),
        os.path.realpath(os.path.join(request.config_dir, "result")),
        request.expected_command[image_index + 1:],
        (actual.get("NetworkSettings") or {}).get("Networks") or {},
        dict(pairs), expected_environment,
    )


def _valid_mount(observed: _ObservedContainer) -> bool:
    mounts = observed.actual.get("Mounts") or []
    by_destination = {row.get("Destination"): row for row in mounts}
    source = by_destination.get("/input/media") or {}
    result = by_destination.get("/scratch") or {}
    return len(mounts) == 2 \
        and source.get("Source") == observed.source \
        and source.get("RW") is False \
        and result.get("Source") == observed.result_dir \
        and result.get("RW") is True


def _valid_host(observed: _ObservedContainer) -> bool:
    required_host = {
        "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
        "CapDrop": ["ALL"], "Memory": PROBE_MEMORY_BYTES,
        "MemorySwap": PROBE_MEMORY_BYTES, "NanoCpus": PROBE_CPUS * 1_000_000_000,
        "PidsLimit": 64, "Init": True,
    }
    host = observed.host
    return (
        all(host.get(key) == value for key, value in required_host.items())
        and host.get("SecurityOpt") == ["no-new-privileges:true"]
        and host.get("CapAdd") in (None, [])
    )


def _valid_identity(
    runtime: DockerRuntime,
    observed: _ObservedContainer,
) -> bool:
    return (
        observed.state.get("Running")
        and observed.actual.get("Image") == runtime.image_id
        and observed.config.get("User") == runtime.user_id
        and observed.config.get("Entrypoint") == ["/usr/bin/node"]
        and observed.config.get("Cmd") == observed.expected_cmd
        and observed.environment == observed.expected_environment
        and len(observed.environment) == len(observed.expected_environment)
        and set(observed.networks) == {"none"}
    )


def attest_probe_container(
    runtime: DockerRuntime,
    *arguments: object,
) -> dict:
    """Reobserve Docker-resolved isolation before accepting decode output."""
    observed = _observed_container(runtime, _probe_attestation(arguments))
    if not (
        _valid_identity(runtime, observed)
        and _valid_host(observed)
        and _valid_mount(observed)
    ):
        raise RuntimeError("external-media probe isolation attestation failed")
    return {
        "imageId": observed.actual["Image"],
        "containerId": observed.actual["Id"],
        "networkMode": observed.host["NetworkMode"],
        "nonrootUser": observed.config["User"],
        "readonlyRoot": observed.host["ReadonlyRootfs"], "mountSource": observed.source,
    }
