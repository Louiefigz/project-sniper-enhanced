#!/bin/bash
# Sniper's own tools: Python, Node, ffmpeg/ffprobe, whisper.cpp, tesseract, yt-dlp and git.
# Sourced by lib/common.sh, never executed directly.
#
# install/deps/osx-arm64.lock names every file with its size and SHA-256. The first install
# downloads them with curl (resumable; each file is checked before it is used) and a
# hash-pinned micromamba installs them offline into ONE private folder per lock:
#     ~/.project-sniper/runtimes/<lock id>/
# The ffmpeg in it is Sniper's own build, shipped in install/deps/ with its source in
# third-party/sources/. Installs of releases with the same lock share the folder; each
# registers itself under <folder>/.sniper-users/ so uninstall removes it only when no
# install uses it any more. Your Homebrew, Python, Node and conda are never read or changed.
#
# This runs BEFORE Sniper's Python exists, so it needs only what macOS itself provides:
# bash, curl, tar, shasum, codesign and lockf. The folder lives under your home folder,
# not inside this package, because Studio needs a Node path without spaces and this
# package's own folder may contain them.

DEPS_LOCK="$PKG_ROOT/install/deps/osx-arm64.lock"
DEPS_HOME="$HOME/.project-sniper"
DEPS_TOOLS="ffmpeg ffprobe whisper-cli tesseract yt-dlp node npm python3 git"

# One header value of the lock ("# min-macos 12.0" -> 12.0).
deps_header() {  # key
  local line
  while IFS= read -r line; do
    case "$line" in "# $1 "*) printf '%s' "${line#"# $1 "}"; return 0 ;; esac
  done < "$DEPS_LOCK"
  return 1
}

# Sets DEPS_ID (first 16 hex of the lock's SHA-256), DEPS_PREFIX and DEPS_RECORD.
deps_paths() {
  [ -f "$DEPS_LOCK" ] || fail "This folder is incomplete: install/deps/osx-arm64.lock is missing."
  case "$HOME" in /*) ;; *) fail "HOME is not set to your home folder; open Terminal normally and run this again." ;; esac
  case "$HOME" in *[[:space:]]*) fail "Your home folder path contains a space ($HOME). Sniper's tools
  must live on a path without spaces, and it keeps them in your home folder." ;; esac
  DEPS_ID="$(sha "$DEPS_LOCK")" || fail "Cannot read install/deps/osx-arm64.lock."
  DEPS_ID="${DEPS_ID:0:16}"
  DEPS_PREFIX="$DEPS_HOME/runtimes/$DEPS_ID"
  DEPS_RECORD="$DEPS_HOME/runtimes/$DEPS_ID.tree.json"
}

# Finished (its completion marker names this lock) and every tool is still there.
deps_ready() {
  local tool
  [ -f "$DEPS_PREFIX/.sniper-runtime-complete" ] \
    && [ "$(cat "$DEPS_PREFIX/.sniper-runtime-complete")" = "$DEPS_ID" ] || return 1
  for tool in $DEPS_TOOLS; do [ -x "$DEPS_PREFIX/bin/$tool" ] || return 1; done
}

# Before anything else: make sure the tools exist, installing them if not (bash only).
# Two installers that need the same folder take turns (lockf); the second one then
# finds it finished. A full integrity check follows inside the maintenance lock.
ensure_runtime_tools() {
  local lockfile rc
  deps_paths
  if deps_ready; then say "Sniper's own tools — present ($DEPS_PREFIX)"; return 0; fi
  mkdir -p "$DEPS_HOME/runtimes" && chmod 700 "$DEPS_HOME" || fail "Cannot create $DEPS_HOME"
  lockfile="$DEPS_HOME/install.lock"   # one tools install at a time, whichever release it is for
  say "Setting up Sniper's own tools in $DEPS_PREFIX"
  say "  (about 310 MB to download once; about 1.2 GB on disk; nothing outside that folder changes)."
  rc=0; /usr/bin/lockf -k -t 0 "$lockfile" /bin/bash "$PKG_ROOT/install/lib/runtime_tools_install.sh" || rc=$?
  if [ "$rc" = 75 ]; then
    say "Another Sniper installer is setting up the same tools; waiting for it to finish."
    rc=0; /usr/bin/lockf -k -t 3600 "$lockfile" /bin/bash "$PKG_ROOT/install/lib/runtime_tools_install.sh" || rc=$?
  fi
  [ "$rc" = 0 ] || exit "$rc"
  deps_ready || fail "Sniper's own tools did not finish installing. Run the installer again; it resumes."
}

deps_user_key() { printf '%s' "$PKG_ROOT" | /usr/bin/shasum -a 256 | awk '{print substr($1, 1, 16)}'; }

# This install uses the folder: record it so uninstall knows who else does.
deps_register() {
  mkdir -p "$DEPS_PREFIX/.sniper-users" && printf '%s' "$PKG_ROOT" > "$DEPS_PREFIX/.sniper-users/$(deps_user_key)"
}

# Uninstall: this install stops using its tools. The folder goes when no other install
# uses it; the downloads and micromamba go with the last folder.
deps_unregister_and_prune() {
  local others
  deps_paths
  rm -f "$DEPS_PREFIX/.sniper-users/$(deps_user_key)"
  others="$(deps_other_users | tr '\n' ' ')"
  if [ -n "${others// }" ]; then
    say "Sniper's own tools stay in $DEPS_PREFIX: another Sniper install uses them ($others)."
    return 0
  fi
  [ -d "$DEPS_HOME" ] || return 0
  /usr/bin/lockf -k -t 0 "$DEPS_HOME/install.lock" /bin/rm -rf "$DEPS_PREFIX" "$DEPS_RECORD" \
      "$DEPS_HOME/runtimes/$DEPS_ID.explicit.txt" \
    || { warn "Sniper's tools are being installed for another Sniper folder right now; $DEPS_PREFIX was left in place."; return 0; }
  if [ -z "$(ls -A "$DEPS_HOME/runtimes" 2>/dev/null)" ]; then
    /usr/bin/lockf -t 0 "$DEPS_HOME/install.lock" /bin/rm -rf "$DEPS_HOME/pkgs" "$DEPS_HOME/tools" \
        "$DEPS_HOME/mamba-home" "$DEPS_HOME/mamba-root" "$DEPS_HOME/runtimes" \
      && rm -f "$DEPS_HOME/install.lock" && rmdir "$DEPS_HOME" 2>/dev/null
  fi
  say "Removed Sniper's own tools ($DEPS_PREFIX)."
}

# Inside the maintenance lock: every file is exactly as installed, and each tool runs.
# A changed or missing file makes this reinstall the folder from the verified downloads.
verify_runtime_tools() {
  local why python="$DEPS_PREFIX/bin/python3"
  deps_paths
  if deps_ready && [ -f "$DEPS_RECORD" ] \
      && why="$("$python" -I -B "$INSTALL_TOOLS" tree-check "$DEPS_PREFIX" "$DEPS_RECORD" $(deps_tree_excludes))"; then
    deps_check_tools || fail "Sniper's own tools do not run: $DEPS_TOOL_PROBLEM. Run the installer again."
    say "Sniper's own tools — verified ($why)"
  else
    say "Sniper's own tools — changed since they were installed (${why:-incomplete}); reinstalling them."
    rm -f "$DEPS_PREFIX/.sniper-runtime-complete"
    ensure_runtime_tools
    deps_check_tools || fail "Sniper's own tools do not run: $DEPS_TOOL_PROBLEM."
  fi
  deps_register
}

# Folders the tools themselves write to after installation (the font cache, Python's
# byte-code caches, the users register and the completion marker).
deps_tree_excludes() {
  printf '%s ' --exclude var/cache/fontconfig --exclude .sniper-users --exclude-name __pycache__ \
    --exclude-file .sniper-runtime-complete
}

# Each tool runs, and ffmpeg has every feature the renderer uses; sets DEPS_TOOL_PROBLEM.
deps_check_tools() {
  local bin="$DEPS_PREFIX/bin" missing
  DEPS_TOOL_PROBLEM=""
  "$bin/ffmpeg" -hide_banner -version >/dev/null 2>&1 || DEPS_TOOL_PROBLEM="ffmpeg does not start"
  "$bin/ffprobe" -hide_banner -version >/dev/null 2>&1 || DEPS_TOOL_PROBLEM="ffprobe does not start"
  "$bin/whisper-cli" --help >/dev/null 2>&1 || DEPS_TOOL_PROBLEM="whisper-cli does not start"
  case " $("$bin/tesseract" --list-langs 2>&1 | tr '\n' ' ') " in *" eng "*) ;; *) DEPS_TOOL_PROBLEM="tesseract has no English data" ;; esac
  "$bin/yt-dlp" --version >/dev/null 2>&1 || DEPS_TOOL_PROBLEM="yt-dlp does not start"
  "$bin/node" --version >/dev/null 2>&1 || DEPS_TOOL_PROBLEM="node does not start"
  "$bin/python3" -I -c 'import ssl, sqlite3' >/dev/null 2>&1 || DEPS_TOOL_PROBLEM="python does not start"
  "$bin/git" --version >/dev/null 2>&1 || DEPS_TOOL_PROBLEM="git does not start"
  [ -n "$DEPS_TOOL_PROBLEM" ] && return 1
  missing="$(ffmpeg_missing_features "$bin/ffmpeg")"
  [ -z "$missing" ] || { DEPS_TOOL_PROBLEM="ffmpeg lacks $missing"; return 1; }
}

# Installs that still use this folder, other than this one.
deps_other_users() {
  local entry other
  [ -d "$DEPS_PREFIX/.sniper-users" ] || return 0
  for entry in "$DEPS_PREFIX/.sniper-users"/*; do
    [ -f "$entry" ] || continue
    other="$(cat "$entry")"
    [ "$other" = "$PKG_ROOT" ] && continue
    [ -f "$other/runtime/sniper.env" ] && [ "$(settings_value SNIPER_DEPS_PREFIX "$other/runtime/sniper.env")" = "$DEPS_PREFIX" ] \
      && printf '%s\n' "$other"
  done
}
