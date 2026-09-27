#!/bin/bash
# The installer's steps. Sourced by install/install.command only.
#
# Every step is safe to interrupt: it records a receipt (what it was built from)
# and, for folders, a record of every file's SHA-256 only after it finished. A
# rerun skips a step only when the receipt matches AND the output still verifies;
# anything missing, partial or changed is removed and redone, with no manual
# cleanup. Downloads resume and are checked against a SHA-256 pinned at build time.

MODEL_NAME="ggml-small.en.bin"
MODEL_SHA="c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"

tree_record() {  # dir record [excluded-subfolder]
  "$PYTHON_BIN" "$INSTALL_TOOLS" tree-record "$1" "$2" ${3:+--exclude "$3"} >/dev/null \
    || fail "Could not record the finished contents of $1."
}
tree_check() {  # dir record [excluded-subfolder]; prints what changed
  "$PYTHON_BIN" "$INSTALL_TOOLS" tree-check "$1" "$2" ${3:+--exclude "$3"}
}

# npm belonging to the validated Node, with runtime/bin (that Node) first on PATH
# so npm itself and every package script run on it.
npm_cli() { PATH="$RUNTIME_BIN:$PATH" "$NPM_BIN" "$@"; }

# The executables this install uses: Sniper's own (lib/runtime_tools.sh), just verified by
# verify_runtime_tools. Whatever Node, Python or ffmpeg this Mac has elsewhere is not used.
use_runtime_tools() {
  local bin="$DEPS_PREFIX/bin" problem ffmpeg_version
  NODE_BIN="$bin/node"
  problem="$(node_problem "$NODE_BIN" "$(release_value components.node_floor)")"
  [ -z "$problem" ] || fail "Sniper's own Node cannot be used: $problem. Run the installer again."
  NODE_VERSION="$(node_version_of "$NODE_BIN")"; NPM_BIN="$bin/npm"
  PYTHON_BIN="$bin/python3"
  PY_VER="$("$PYTHON_BIN" -I -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')" \
    || fail "Sniper's own Python does not start. Run the installer again."
  TOOL_FFMPEG="$bin/ffmpeg"; TOOL_FFPROBE="$bin/ffprobe"; TOOL_WHISPER_CLI="$bin/whisper-cli"
  TOOL_TESSERACT="$bin/tesseract"; TOOL_YT_DLP="$bin/yt-dlp"
  ffmpeg_version="$(first_line "$("$TOOL_FFMPEG" -hide_banner -version 2>/dev/null)")"
  say "Node $NODE_VERSION, Python $PY_VER, ${ffmpeg_version%% Copyright*}, whisper.cpp, tesseract, yt-dlp and git"
  say "  — Sniper's own, in $DEPS_PREFIX"
}

# runtime/bin: links to exactly the executables validated above. It comes first on
# the generated PATH, so "#!/usr/bin/env node" scripts, npm scripts and every
# worker a Sniper command spawns by name run these — never a different copy that
# happens to sit in the same folder as one of them.
link_runtime_bin() {
  rm -rf "$RUNTIME_BIN.tmp" && mkdir -p "$RUNTIME_BIN.tmp" || fail "Cannot create $RUNTIME_BIN"
  ln -s "$NODE_BIN" "$RUNTIME_BIN.tmp/node"
  ln -s "$TOOL_FFMPEG" "$RUNTIME_BIN.tmp/ffmpeg"; ln -s "$TOOL_FFPROBE" "$RUNTIME_BIN.tmp/ffprobe"
  ln -s "$TOOL_WHISPER_CLI" "$RUNTIME_BIN.tmp/whisper-cli"
  ln -s "$TOOL_TESSERACT" "$RUNTIME_BIN.tmp/tesseract"; ln -s "$TOOL_YT_DLP" "$RUNTIME_BIN.tmp/yt-dlp"
  rm -rf "$RUNTIME_BIN" && mv "$RUNTIME_BIN.tmp" "$RUNTIME_BIN" || fail "Cannot create $RUNTIME_BIN"
}

npm_step() {  # label dir receipt-name
  local key why record="$RECEIPTS/$3.tree.json"
  key="node-$NODE_VERSION@$NODE_BIN|lock-$(sha "$2/package-lock.json")"
  if receipt_ok "$3" "$key"; then
    why="$(tree_check "$2/node_modules" "$record" .cache)" && { say "$1 — up to date (verified)"; return 0; }
    say "$1 — changed since it was installed ($why); reinstalling"
  fi
  clear_receipt "$3"
  # npm ci can fail on a half-extracted tree (ENOENT on chmod inside a partially
  # written package), so whatever an interrupted attempt left is removed first.
  rm -rf "$2/node_modules"
  ( cd "$2" && npm_cli ci --no-audit --no-fund ) || fail "Installing $1 failed.
  Check your connection and run the installer again; it repeats this step."
  tree_record "$2/node_modules" "$record" .cache
  write_receipt "$3" "$key"; say "$1 — installed"
}

python_step() {
  local lock="$PKG_ROOT/install/requirements.lock.txt" key why venv="$APP_DIR/.venv/bin/python3"
  key="python-$PY_VER@$PYTHON_BIN|lock-$(sha "$lock")"
  if receipt_ok venv "$key" && [ -x "$venv" ]; then
    why="$("$venv" -I "$INSTALL_TOOLS" venv-check "$lock")" && { say "Python environment — up to date ($why)"; return 0; }
    say "Python environment — changed since it was installed ($why); rebuilding"
  fi
  clear_receipt venv
  rm -rf "$APP_DIR/.venv"   # rebuilt from scratch: a partial venv is never reused
  "$PYTHON_BIN" -m venv "$APP_DIR/.venv" || fail "Could not create the Python environment."
  "$venv" -m pip install --disable-pip-version-check --no-input -q \
      --require-hashes --only-binary=:all: -r "$lock" \
    || fail "Installing the pinned Python packages failed. Each download is checked against
  the SHA-256 recorded for this release. Check your connection and run the installer again."
  why="$("$venv" -I "$INSTALL_TOOLS" venv-check "$lock")" || fail "The new Python environment does not verify: $why"
  write_receipt venv "$key"; say "Python environment — installed ($why)"
}

browser_runs() {
  local out
  [ -x "$BROWSER_BIN" ] && out="$("$BROWSER_BIN" --version 2>/dev/null)" || return 1
  case "$out" in *"$1"*) return 0 ;; esac
  return 1
}

browser_step() {
  local pin platform prefix sha url dir key why archive record="$RECEIPTS/browser.tree.json"
  pin="$(release_value components.chrome_headless_shell)"
  platform="$SNIPER_BROWSER_PLATFORM"; prefix="$SNIPER_BROWSER_PREFIX"
  sha="$(release_value "components.chrome_headless_shell_sha256.$platform")"
  url="${SNIPER_BROWSER_BASE_URL:-https://storage.googleapis.com/chrome-for-testing-public}/$pin/$platform/chrome-headless-shell-$platform.zip"
  dir="$BROWSER_CACHE/chrome-headless-shell/$prefix-$pin"
  BROWSER_BIN="$dir/chrome-headless-shell-$platform/chrome-headless-shell"
  key="$pin|$sha"
  if receipt_ok browser "$key"; then
    why="$(tree_check "$dir" "$record")" && browser_runs "$pin" \
      && { say "chrome-headless-shell $pin — up to date (verified)"; return 0; }
    say "chrome-headless-shell $pin — changed since it was installed (${why:-it no longer starts}); reinstalling"
  fi
  clear_receipt browser
  archive="$BROWSER_CACHE/chrome-headless-shell-$platform-$pin.zip"
  mkdir -p "$BROWSER_CACHE"
  download_verified "$url" "$archive" "$sha" "the rendering browser $pin (about 90 MB)"
  rm -rf "$dir" "$dir.extracting" && mkdir -p "$dir.extracting"
  /usr/bin/ditto -x -k "$archive" "$dir.extracting" || { rm -rf "$dir.extracting"; fail "Unpacking the rendering browser failed. Run the installer again."; }
  mv "$dir.extracting" "$dir"
  browser_runs "$pin" || fail "The rendering browser does not start. Run the installer again."
  tree_record "$dir" "$record"
  rm -f "$archive"
  write_receipt browser "$key"; say "chrome-headless-shell $pin — installed (SHA-256 verified)"
}

model_step() {
  local existing url
  MODEL_PATH="$WHISPER_DIR/$MODEL_NAME"
  url="${SNIPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL_NAME}"
  mkdir -p "$WHISPER_DIR"
  if [ -f "$MODEL_PATH" ] && [ "$(sha "$MODEL_PATH")" != "$MODEL_SHA" ]; then
    say "The speech model at $MODEL_PATH does not match its checksum; replacing it."
    rm -f "$MODEL_PATH"
  fi
  [ -f "$MODEL_PATH" ] || clear_receipt model
  # Reuse an identical copy already on this Mac (verified by hash, cloned on APFS).
  for existing in "$HOME/.cache/hyperframes/whisper/models/$MODEL_NAME" \
                  "/opt/homebrew/share/whisper-cpp/models/$MODEL_NAME" \
                  "/usr/local/share/whisper-cpp/models/$MODEL_NAME"; do
    [ -f "$MODEL_PATH" ] && break
    if [ -f "$existing" ] && [ "$(sha "$existing")" = "$MODEL_SHA" ]; then
      cp -c "$existing" "$MODEL_PATH.part" 2>/dev/null || cp "$existing" "$MODEL_PATH.part"
      mv "$MODEL_PATH.part" "$MODEL_PATH"; say "Found an identical speech model already on this Mac; reused it."
    fi
  done
  [ -f "$MODEL_PATH" ] || download_verified "$url" "$MODEL_PATH" "$MODEL_SHA" "the speech model (about 465 MB)"
  write_receipt model "$MODEL_SHA"; say "Speech model verified"
}
