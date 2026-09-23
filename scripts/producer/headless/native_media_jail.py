"""In-jail launcher for native media admission (run as a script, stdlib only).

    python3 -I -S -B native_media_jail.py <request.json> <attest-fd> -- <decoder> [args...]
    python3 -I -S -B native_media_jail.py <request.json> <attest-fd> -- inspect

Everything that touches untrusted bytes runs after this process has confined
itself. Order matters and is the point of this file:

1. set resource limits that survive exec (no core files, 256 descriptors, a CPU
   ceiling -- on macOS this raises one SIGXCPU, a stop request) and an alarm
   that terminates the process if its supervisor disappears;
2. apply the generated Seatbelt profile to *this* process
   (`sandbox_init_with_parameters`) after checking its hash;
3. write a one-line attestation (mode, decoder, input, limits) to ``attest-fd``,
   then forbid regular-file writes (RLIMIT_FSIZE 0; set last because it would
   block that write);
4. either replace this process with the decoder through ``posix_spawn`` with
   ``POSIX_SPAWN_SETEXEC`` and a fatal jetsam memory limit, or (``inspect``)
   run the font/SVG recogniser on the one readable input and print its result.

The jetsam limit must be attached at that final exec: macOS resets a spawn-time
limit on any later exec, and neither a parent nor the process itself may set one
afterwards. Because an exploited decoder could exec itself again to shed it, the
supervisor also watches this pid's physical footprint and CPU time and kills the
process group above the ceilings (native_media_sandbox.py).
"""
import ctypes
import hashlib
import json
import math
import os
import re
import resource
import signal
import struct
import sys

_LIBC = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
_SETEXEC, _SETSIGDEF, _SETSIGMASK, _CLOEXEC_DEFAULT = 0x0040, 0x0004, 0x0008, 0x4000
_JETSAM_FATAL = 0x04 | 0x08  # active and inactive memory limits are fatal
_PARAMS = ("DECODER", "INPUT")
_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true")
_SVG_ACTIVE = re.compile(r"<!doctype|<!entity|<script|javascript:|https?://|onload\s*=|onerror\s*=|<foreignobject")
_SVG_OPEN = re.compile(r"<svg(?![A-Za-z0-9_])", re.I)
_VIEWBOX = re.compile(r"(?<![A-Za-z0-9_])viewBox\s*=\s*[\"']\s*[\d.+-]+\s+[\d.+-]+\s+([\d.]+)\s+([\d.]+)\s*[\"']", re.I)
_WIDTH = re.compile(r"(?<![A-Za-z0-9_])width\s*=\s*[\"']([\d.]+)", re.I)
_HEIGHT = re.compile(r"(?<![A-Za-z0-9_])height\s*=\s*[\"']([\d.]+)", re.I)


def _fail(code, message):
    """Exit before exec with a reason the supervisor can classify."""
    os.write(2, ("native-media-jail: " + message + "\n").encode("utf-8", "replace"))
    os._exit(code)


def _limits(request):
    """Resource ceilings inherited by the decoder across exec, plus the orphan alarm."""
    cpu = int(request["cpuSeconds"])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
    signal.alarm(int(math.ceil(float(request["wallSeconds"]))) + 5)  # pending alarms survive exec
    applied = {name: list(resource.getrlimit(getattr(resource, name)))
               for name in ("RLIMIT_CORE", "RLIMIT_NOFILE", "RLIMIT_CPU")}
    applied["RLIMIT_FSIZE"] = [0, 0]  # applied after the attestation is written, before any input is read
    return applied


def _apply_profile(profile_text, parameters):
    """Apply the Seatbelt profile to this process; fail closed on any error."""
    init = _LIBC.sandbox_init_with_parameters
    init.argtypes = [ctypes.c_char_p, ctypes.c_uint64,
                     ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_char_p)]
    flat = []
    for key in _PARAMS:
        flat.extend((key.encode("utf-8"), parameters[key].encode("utf-8")))
    array = (ctypes.c_char_p * (len(flat) + 1))(*flat, None)
    error = ctypes.c_char_p()
    if init(profile_text.encode("utf-8"), 0, array, ctypes.byref(error)) != 0:
        _fail(70, "sandbox profile was not applied: %s" % (error.value or b"").decode("utf-8", "replace"))
    check = _LIBC.sandbox_check
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    if check(os.getpid(), None, 0) != 1:
        _fail(70, "process is not sandboxed after the profile was applied")


def _spawn_attributes(memory_mib):
    """Spawn attributes: replace this image, default signals, fatal jetsam limit."""
    attr, actions = ctypes.c_void_p(), ctypes.c_void_p()
    _LIBC.posix_spawnattr_init(ctypes.byref(attr))
    _LIBC.posix_spawn_file_actions_init(ctypes.byref(actions))
    for descriptor in (0, 1, 2):
        _LIBC.posix_spawn_file_actions_addinherit_np(ctypes.byref(actions), descriptor)
    empty, full = ctypes.c_uint32(0), ctypes.c_uint32(0xFFFFFFFF)
    _LIBC.posix_spawnattr_setsigmask(ctypes.byref(attr), ctypes.byref(empty))
    _LIBC.posix_spawnattr_setsigdefault(ctypes.byref(attr), ctypes.byref(full))
    flags = _SETEXEC | _SETSIGDEF | _SETSIGMASK | _CLOEXEC_DEFAULT
    if _LIBC.posix_spawnattr_setflags(ctypes.byref(attr), ctypes.c_short(flags)) != 0:
        _fail(71, "spawn flags were rejected")
    jetsam = _LIBC.posix_spawnattr_setjetsam_ext
    jetsam.argtypes = [ctypes.c_void_p, ctypes.c_short, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    if jetsam(ctypes.byref(attr), _JETSAM_FATAL, -1, memory_mib, memory_mib) != 0:
        _fail(71, "memory limit was rejected")
    return attr, actions


def _exec_decoder(argv, memory_mib):
    """Replace this process with the decoder; returns only on failure."""
    attr, actions = _spawn_attributes(memory_mib)
    raw = [item.encode("utf-8") for item in argv]
    c_argv = (ctypes.c_char_p * (len(raw) + 1))(*raw, None)
    env = [b"PATH=/usr/bin:/bin", b"LANG=C.UTF-8", b"LC_ALL=C.UTF-8", b"TZ=UTC"]
    c_env = (ctypes.c_char_p * (len(env) + 1))(*env, None)
    pid = ctypes.c_int()
    code = _LIBC.posix_spawn(ctypes.byref(pid), raw[0], ctypes.byref(actions), ctypes.byref(attr), c_argv, c_env)
    _fail(72, "decoder exec failed with error %d" % code)


def _number(text):
    """``Number(text)`` for the decimal strings the SVG patterns capture."""
    try:
        return float(text)
    except ValueError:
        return math.nan


def _integral(value):
    return int(value) if math.isfinite(value) and value == int(value) else value


def _font(head, size):
    """Bounded table-directory check for TrueType/OpenType fonts."""
    tables = struct.unpack_from(">H", head, 4)[0] if len(head) >= 6 else 0
    if tables < 1 or tables > 128 or 12 + tables * 16 > len(head):
        return {"rejected": "FONT_TABLE_LIMIT"}
    for index in range(tables):
        offset, length = struct.unpack_from(">II", head, 12 + index * 16 + 8)
        if offset + length > size:
            return {"rejected": "FONT_TABLE_RANGE"}
    return {"special": {"mediaKind": "font", "durationSeconds": 0, "sizeBytes": size, "width": 0, "height": 0,
                        "videoStreams": 0, "audioStreams": 0, "streamCount": 1, "declaredFrames": 0}}


def _svg_tag(text):
    """The first ``<svg ...>`` start tag, found in one linear pass."""
    for match in _SVG_OPEN.finditer(text):
        end = text.find(">", match.end())
        return text[match.start():end + 1] if end >= 0 else ""
    return ""


def _svg(path, size, limits):
    """Refuse active or remote SVG content and bound its declared size (linear time)."""
    if size > 16 * 1024 * 1024:
        return {"rejected": "SVG_SIZE_LIMIT"}
    with open(path, "rb") as handle:
        text = handle.read(size + 1).decode("utf-8", errors="replace")
    lower = text.lower()
    remote = lower.replace("http://www.w3.org/2000/svg", "").replace("http://www.w3.org/1999/xlink", "")
    if "<svg" not in lower or _SVG_ACTIVE.search(remote):
        return {"rejected": "SVG_ACTIVE_CONTENT"}
    tag = _svg_tag(text)
    view, width_match, height_match = _VIEWBOX.search(tag), _WIDTH.search(tag), _HEIGHT.search(tag)
    width = _number(width_match.group(1)) if width_match else (_number(view.group(1)) if view else 0.0)
    height = _number(height_match.group(1)) if height_match else (_number(view.group(2)) if view else 0.0)
    if not (width > 0 and height > 0) or width > limits["maxWidth"] or height > limits["maxHeight"]:
        return {"rejected": "DIMENSION_LIMIT"}
    return {"special": {"mediaKind": "svg", "durationSeconds": 0, "sizeBytes": size, "width": _integral(width),
                        "height": _integral(height), "videoStreams": 1, "audioStreams": 0, "streamCount": 1,
                        "declaredFrames": 1}}


def _inspect(path, limits):
    """Font/SVG recognition of the one readable input; None for media the decoder must handle."""
    size = os.stat(path).st_size
    if size <= 0 or size > limits["maxBytes"]:
        return {"rejected": "SIZE_LIMIT"}
    with open(path, "rb") as handle:
        head = handle.read(min(65536, size))
    if head[:4] in _FONT_MAGIC:
        return _font(head, size)
    prefix = head[:1024].decode("utf-8", errors="replace").lstrip().lower()
    if prefix.startswith("<svg") or prefix.startswith("<?xml"):
        return _svg(path, size, limits)
    return {"special": None}


def _request(argv):
    """Load and cross-check the supervisor's request."""
    if len(argv) < 5 or argv[3] != "--":
        _fail(64, "usage: native_media_jail.py request.json attest-fd -- decoder args | inspect")
    with open(argv[1], "rb") as handle:
        request = json.loads(handle.read(65536))
    parameters, target = request["parameters"], argv[4:]
    inspect = target == ["inspect"]
    if set(parameters) != set(_PARAMS) or type(request.get("inputPath")) is not str \
            or os.path.realpath(request["inputPath"]) != parameters["INPUT"] \
            or request.get("mode") != ("inspect" if inspect else "exec") \
            or (inspect and parameters["DECODER"] != "/dev/null") or (not inspect and target[0] != parameters["DECODER"]):
        _fail(64, "mode, decoder and jail parameters disagree")
    with open(request["profilePath"], "rb") as handle:
        profile = handle.read(4 * 1024 * 1024)
    if hashlib.sha256(profile).hexdigest() != request["profileSha256"]:
        _fail(64, "jail profile does not match the generated text")
    return request, profile.decode("utf-8"), target, int(argv[2])


def main():
    """Confine this process, attest, then exec the decoder or inspect the input."""
    request, profile, target, attest_fd = _request(sys.argv)
    parameters = request["parameters"]
    rlimits = _limits(request)
    _apply_profile(profile, parameters)
    attestation = {"sandboxed": True, "mode": request["mode"], "rlimits": rlimits,
                   "memoryMiB": request["memoryMiB"], "profileSha256": request["profileSha256"],
                   "decoder": parameters["DECODER"], "input": request["inputPath"],
                   "inputResolved": parameters["INPUT"], "pid": os.getpid()}
    os.write(attest_fd, (json.dumps(attestation, sort_keys=True) + "\n").encode("utf-8"))
    os.fsync(attest_fd)
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    if resource.getrlimit(resource.RLIMIT_FSIZE) != (0, 0):
        _fail(70, "file-size limit was not applied")
    if request["mode"] == "inspect":
        os.write(1, (json.dumps(_inspect(parameters["INPUT"], request["limits"])) + "\n").encode("utf-8"))
        os._exit(0)
    _exec_decoder(target, int(request["memoryMiB"]))


if __name__ == "__main__":
    main()
