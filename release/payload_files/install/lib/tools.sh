#!/bin/bash
# Validating the executables Sniper uses. Since rc4 they are all Sniper's own
# (lib/runtime_tools.sh); nothing is looked up on this Mac's PATH.
# Sourced by lib/common.sh, never executed directly.

# version_ge A B — true when dotted version A >= B (numeric, missing parts = 0).
version_ge() {
  local a="$1" b="$2" x y
  while [ -n "$a$b" ]; do
    x="${a%%.*}"; y="${b%%.*}"
    [ "$a" = "$x" ] && a="" || a="${a#*.}"
    [ "$b" = "$y" ] && b="" || b="${b#*.}"
    x="${x:-0}"; y="${y:-0}"
    case "$x$y" in *[!0-9]*) return 1 ;; esac
    [ "$((10#$x))" -gt "$((10#$y))" ] && return 0
    [ "$((10#$x))" -lt "$((10#$y))" ] && return 1
  done
  return 0
}

# first_line TEXT — the text up to its first newline (no pipe: under pipefail a
# reader that stops early, like head or grep -q, can fail the whole pipeline).
first_line() { printf '%s' "${1%%$'\n'*}"; }

# "22.13.0" from a node binary, or nothing.
node_version_of() {
  local out
  out="$("$1" --version 2>/dev/null)" || return 1
  out="$(first_line "$out")"; out="${out#v}"
  case "$out" in [0-9]*.[0-9]*.[0-9]*) printf '%s' "$out" ;; *) return 1 ;; esac
}

# Why this node executable is unusable for this release, or nothing if it is fine.
# The floor comes from RELEASE.json, computed at build time from every package's
# engines.node in both lockfiles. Studio identifies its preview server by a
# whitespace-free command line ending in "node", so the path must be one.
node_problem() {  # path floor
  local version
  [ -x "$1" ] || { printf 'not an executable file: %s' "$1"; return 0; }
  version="$(node_version_of "$1")" || { printf '%s does not report a Node version' "$1"; return 0; }
  version_ge "$version" "$2" || { printf 'Node %s at %s is older than %s, the oldest version every dependency of this release accepts' "$version" "$1" "$2"; return 0; }
  case "$1" in *[[:space:]]*) printf 'the Node path %s contains a space; Studio cannot identify a preview server started from it' "$1"; return 0 ;; esac
  [ "$(basename "$1")" = node ] || printf 'the Node executable %s is not named node' "$1"
}

python_ok() {
  "$1" -I -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1
}

# Sniper's own Python (lib/runtime_tools.sh), once installed; never a Python from this Mac.
find_python() {
  [ -n "${DEPS_PREFIX:-}" ] || deps_paths
  [ -x "$DEPS_PREFIX/bin/python3" ] && python_ok "$DEPS_PREFIX/bin/python3" || return 1
  printf '%s' "$DEPS_PREFIX/bin/python3"
}

# Every filter and encoder the render chain actually uses, checked on the
# ffmpeg this install will run — not assumed from a version string.
FFMPEG_FILTERS="rubberband zscale subtitles ass drawtext arnndn loudnorm ebur128 afftdn acompressor alimiter sidechaincompress aresample amix overlay crop"
# Matched in the shell, not with `printf | grep -q`: under pipefail grep -q exiting
# at the first match can SIGPIPE the writer and report a present filter as missing
# (seen under load in the rc4 repair runs).
ffmpeg_missing_features() {
  local have enc f e
  have="$("$1" -hide_banner -filters 2>/dev/null | awk '{print $2}')"
  enc="$("$1" -hide_banner -encoders 2>/dev/null | awk '{print $2}')"
  for f in $FFMPEG_FILTERS; do
    case "
$have
" in *"
$f
"*) ;; *) printf '%s ' "$f" ;; esac
  done
  for e in libx264 aac; do
    case "
$enc
" in *"
$e
"*) ;; *) printf '%s ' "$e" ;; esac
  done
}
