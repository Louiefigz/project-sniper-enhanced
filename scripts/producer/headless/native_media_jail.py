"""In-jail launcher for native media admission (run as a script, stdlib only).

    python3 -I -S -B native_media_jail.py <request.json> <attest-fd> -- <decoder> [args...]

Order matters and is the point of this file:

1. set resource limits that survive exec (no core files, 256 descriptors, a CPU
   ceiling -- on macOS this raises one SIGXCPU, which ffmpeg treats as a stop
   request; the supervisor's wall-clock deadline is the enforced time bound);
2. apply the Seatbelt profile to *this* process (`sandbox_init_with_parameters`);
3. write a one-line attestation to ``attest-fd``, then forbid regular-file writes
   (RLIMIT_FSIZE 0; set last because it would block that write);
4. replace this process with the decoder through ``posix_spawn`` with
   ``POSIX_SPAWN_SETEXEC`` and a fatal jetsam memory limit.

The memory limit must be attached at that final exec: macOS resets a spawn-time
limit on any later exec, and neither a parent nor the process itself may set one
afterwards (both return EPERM for an unprivileged user). Nothing untrusted is read
before step 4; the decoder is the first code to touch the input.
"""
import ctypes
import hashlib
import json
import os
import resource
import sys

_LIBC = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
_SETEXEC = 0x0040
_SETSIGDEF = 0x0004
_SETSIGMASK = 0x0008
_CLOEXEC_DEFAULT = 0x4000
_JETSAM_FATAL = 0x04 | 0x08  # active and inactive memory limits are fatal
_PARAMS = ("DECODER", "LIBROOT", "LINKROOT", "INPUT")


def _fail(code, message):
    """Exit before exec with a reason the supervisor can classify."""
    os.write(2, ("native-media-jail: " + message + "\n").encode("utf-8", "replace"))
    os._exit(code)


def _limits(request):
    """Resource ceilings inherited by the decoder across exec."""
    cpu = int(request["cpuSeconds"])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
    applied = {name: list(resource.getrlimit(getattr(resource, name)))
               for name in ("RLIMIT_CORE", "RLIMIT_NOFILE", "RLIMIT_CPU")}
    # RLIMIT_FSIZE is set after the attestation is written (it would block that
    # write) and before exec; the decoder never starts unless it was applied.
    applied["RLIMIT_FSIZE"] = [0, 0]
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
    empty = ctypes.c_uint32(0)
    full = ctypes.c_uint32(0xFFFFFFFF)
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
    code = _LIBC.posix_spawn(ctypes.byref(pid), raw[0], ctypes.byref(actions),
                             ctypes.byref(attr), c_argv, c_env)
    _fail(72, "decoder exec failed with error %d" % code)


def main():
    """Validate the request, confine this process, attest, then exec the decoder."""
    if len(sys.argv) < 5 or sys.argv[3] != "--":
        _fail(64, "usage: native_media_jail.py request.json attest-fd -- decoder args")
    with open(sys.argv[1], "rb") as handle:
        request = json.loads(handle.read(65536))
    attest_fd, argv = int(sys.argv[2]), sys.argv[4:]
    parameters = request["parameters"]
    if argv[0] != parameters["DECODER"] or set(parameters) != set(_PARAMS):
        _fail(64, "decoder and jail parameters disagree")
    with open(request["profilePath"], "rb") as handle:
        profile = handle.read(65536)
    if hashlib.sha256(profile).hexdigest() != request["profileSha256"]:
        _fail(64, "jail profile does not match the approved text")
    rlimits = _limits(request)
    _apply_profile(profile.decode("utf-8"), parameters)
    attestation = {"sandboxed": True, "rlimits": rlimits, "memoryMiB": request["memoryMiB"],
                   "profileSha256": request["profileSha256"], "decoder": argv[0], "pid": os.getpid()}
    os.write(attest_fd, (json.dumps(attestation, sort_keys=True) + "\n").encode("utf-8"))
    os.fsync(attest_fd)
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    if resource.getrlimit(resource.RLIMIT_FSIZE) != (0, 0):
        _fail(70, "file-size limit was not applied")
    _exec_decoder(argv, int(request["memoryMiB"]))


if __name__ == "__main__":
    main()
