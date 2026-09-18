#!/bin/bash
# The executables Sniper uses but does not install: finding and validating them.
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
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1
}

find_python() {
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$(command -v "$candidate")"; then
      command -v "$candidate"; return 0
    fi
  done
  return 1
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

# Tools a feature needs, with the Homebrew formula that provides each and the
# feature that refuses to run without it. The doctor checks the same list.
#   tool        formula      needed by
EXTERNAL_TOOLS="ffmpeg:ffmpeg:every render
ffprobe:ffmpeg:every render
whisper-cli:whisper-cpp:local transcription
tesseract:tesseract:reference study (on-screen text reading)
yt-dlp:yt-dlp:adding a reference from a URL"

# The executable a tool name resolves to, only if it actually runs.
tool_runs() {  # name
  local path
  path="$(command -v "$1")" || return 1
  case "$1" in
    ffmpeg|ffprobe) "$path" -version >/dev/null 2>&1 ;;
    whisper-cli) "$path" --help >/dev/null 2>&1 ;;
    *) "$path" --version >/dev/null 2>&1 ;;
  esac || return 1
  printf '%s' "$path"
}
