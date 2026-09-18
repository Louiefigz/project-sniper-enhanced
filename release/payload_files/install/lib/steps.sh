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

brew_hint() {
  if command -v brew >/dev/null 2>&1; then say "  Install it with:   brew install $1"
  else say "  Homebrew is not installed. Either install Homebrew from https://brew.sh and run
  'brew install $1', or install $1 another way and make sure it is on your PATH."; fi
}

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

node_missing() {  # floor reason
  say "Node $1 or newer is required; $2."
  say "  Download the LTS version (Node $(release_value components.node_recommended)) from https://nodejs.org."
  say "  If your Node comes from nvm, fnm or volta, run this installer from Terminal, where"
  say "  that Node is on your PATH; the app then uses the same Node when started from Finder."
  fail "Node is missing or not usable."
}

# Choose the ONE Node this install uses and record the real binary it runs
# (process.execPath), so a shim or a per-shell symlink resolves to a durable file.
select_node() {
  local floor found problem unsupported
  floor="$(release_value components.node_floor)"
  found="$(command -v node)" || node_missing "$floor" "none was found on PATH"
  problem="$(node_problem "$found" "$floor")"
  case "$problem" in *"older than"*|*"does not report"*) node_missing "$floor" "$problem" ;; esac
  NODE_BIN="$("$found" -p 'require("fs").realpathSync(process.execPath)' 2>/dev/null)" \
    || node_missing "$floor" "$found did not run"
  problem="$(node_problem "$NODE_BIN" "$floor")"
  [ -z "$problem" ] || node_missing "$floor" "$problem"
  NODE_VERSION="$(node_version_of "$NODE_BIN")"
  unsupported=" $(release_value components.node_unsupported_majors) "
  case "$unsupported" in *" ${NODE_VERSION%%.*} "*)
    warn "Node $NODE_VERSION is outside the range some of this release's dependencies declare.
  It is not refused, but Node $(release_value components.node_recommended) (LTS) is recommended." ;;
  esac
  NPM_BIN="$(dirname "$NODE_BIN")/npm"
  [ -x "$NPM_BIN" ] || NPM_BIN="$(command -v npm)" || fail "npm was not found next to $NODE_BIN or on PATH."
  say "Node $NODE_VERSION — ok ($NODE_BIN; this release needs $floor or newer)"
}

# Every external tool must be present and actually run; all missing ones are listed at once.
check_external_tools() {
  local line name formula feature path missing=""
  while IFS= read -r line; do
    name="${line%%:*}"; formula="${line#*:}"; feature="${formula#*:}"; formula="${formula%%:*}"
    if path="$(tool_runs "$name")"; then
      eval "TOOL_$(printf '%s' "$name" | tr 'a-z-' 'A-Z_')=\$path"
      continue
    fi
    say "$name is required for $feature and was not found on your PATH (or did not run)."
    brew_hint "$formula"
    missing="$missing $name"
  done <<EOF
$EXTERNAL_TOOLS
EOF
  [ -z "$missing" ] || fail "Missing:$missing. Install them, then run the installer again."
  MISSING="$(ffmpeg_missing_features "$TOOL_FFMPEG")"
  if [ -n "$MISSING" ]; then
    say "Your ffmpeg ($TOOL_FFMPEG) lacks features the renderer uses: $MISSING"
    say "  The Homebrew build includes them. Other builds must be configured with"
    say "  libass, libfreetype, librubberband, libzimg and libx264."
    fail "ffmpeg is missing required features."
  fi
  say "ffmpeg, whisper-cli, tesseract and yt-dlp — ok"
}

# runtime/bin: links to exactly the executables validated above. It comes first on
# the generated PATH, so the pinned CLIs' "#!/usr/bin/env node", npm scripts and
# every worker the app spawns by name run these — never a different copy that
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

# fetch_part URL PART SHA256 — 0: PART is complete and correct; 1: it is complete
# but wrong; 2: the transfer stopped part-way (a connection problem; PART keeps what
# arrived); 3: the server refused to continue an existing PART (HTTP error, e.g. 416
# for a partial file longer than the real one) without adding a byte.
fetch_part() {
  local before=0 after=0 rc=0
  [ -f "$2" ] && before="$(stat -f %z "$2")"
  curl -fL --retry 3 --retry-delay 2 -C - -o "$2" "$1" || rc=$?
  if [ "$rc" = 0 ]; then
    [ "$(sha "$2")" = "$3" ] && return 0
    return 1
  fi
  [ -f "$2" ] && [ "$(sha "$2")" = "$3" ] && return 0   # already complete: the server said 416
  [ -f "$2" ] && after="$(stat -f %z "$2")"
  case "$rc" in 22|33|36) [ "$before" -gt 0 ] && [ "$after" = "$before" ] && return 3 ;; esac
  return 2
}

# download_verified URL TARGET SHA256 LABEL — resumable; the file appears at
# TARGET only once its SHA-256 matches. A partial file that proves wrong or cannot
# be resumed is discarded and fetched once more from the start, in the same run.
download_verified() {
  local url="$1" target="$2" want="$3" label="$4" part="$2.part" rc
  if [ -f "$target" ] && [ "$(sha "$target")" = "$want" ]; then return 0; fi
  rm -f "$target"
  if [ -f "$part" ]; then say "Resuming $label from $(stat -f %z "$part") bytes."; else say "Downloading $label."; fi
  fetch_part "$url" "$part" "$want"; rc=$?
  if [ "$rc" = 1 ] || [ "$rc" = 3 ]; then
    rm -f "$part"; say "The partial download was not usable; downloading $label again from the beginning."
    fetch_part "$url" "$part" "$want"; rc=$?
  fi
  case "$rc" in
    0) mv "$part" "$target"; return 0 ;;
    2) fail "Downloading $label stopped before it finished; the $(stat -f %z "$part" 2>/dev/null || echo 0) bytes
  received are kept. Run the installer again when your connection is stable; it resumes." ;;
  esac
  rm -f "$part"
  fail "Downloading $label produced the wrong file (checksum mismatch); it was deleted.
  Run the installer again to download it afresh."
}

browser_runs() { [ -x "$BROWSER_BIN" ] && "$BROWSER_BIN" --version 2>/dev/null | grep -q "$1"; }

browser_step() {
  local pin platform prefix sha url dir key why archive record="$RECEIPTS/browser.tree.json"
  pin="$(release_value components.chrome_headless_shell)"
  case "$(uname -m)" in arm64) platform=mac-arm64; prefix=mac_arm ;; *) platform=mac-x64; prefix=mac ;; esac
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

cli_ok() {  # name expected-version-line
  [ -x "$CLI_BIN/$1" ] && [ "$(PATH="$RUNTIME_BIN:$PATH" CODEX_HOME="$CODEX_HOME_LOCAL" \
    CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR_LOCAL" "$CLI_BIN/$1" --version 2>/dev/null | head -1)" = "$2" ]
}

# The two CLIs come from install/cli/package-lock.json, whose integrity hashes
# npm ci checks for every tarball (the CLIs' native binaries included).
cli_step() {
  local codex_want claude_want key why lockdir="$PKG_ROOT/install/cli" record="$RECEIPTS/cli.tree.json"
  codex_want="$(release_value components.codex_cli_admitted)"; claude_want="$(release_value components.claude_cli_admitted)"
  mkdir -p "$CLAUDE_CONFIG_DIR_LOCAL" "$CODEX_HOME_LOCAL"; chmod 700 "$CLAUDE_CONFIG_DIR_LOCAL" "$CODEX_HOME_LOCAL"
  key="$codex_want|$claude_want|lock-$(sha "$lockdir/package-lock.json")|node-$NODE_VERSION@$NODE_BIN"
  if receipt_ok cli "$key"; then
    why="$(tree_check "$CLI_PREFIX/node_modules" "$record")" && cli_ok codex "$codex_want" \
      && cli_ok claude "$claude_want" && { say "Codex and Claude CLIs — up to date (verified)"; return 0; }
    say "Codex and Claude CLIs — changed since they were installed (${why:-a CLI no longer reports its pinned version}); reinstalling"
  fi
  clear_receipt cli
  rm -rf "$CLI_PREFIX" && mkdir -p "$CLI_PREFIX" || fail "Cannot create $CLI_PREFIX"
  cp "$lockdir/package.json" "$lockdir/package-lock.json" "$CLI_PREFIX/" || fail "install/cli is incomplete."
  ( cd "$CLI_PREFIX" && npm_cli ci --no-audit --no-fund --silent ) \
    || fail "Installing the pinned CLIs failed. Run the installer again."
  cli_ok codex "$codex_want" || fail "The Codex CLI does not report '$codex_want'."
  cli_ok claude "$claude_want" || fail "The Claude CLI does not report '$claude_want'."
  tree_record "$CLI_PREFIX/node_modules" "$record"
  write_receipt cli "$key"; say "Codex and Claude CLIs — installed ($codex_want; $claude_want)"
}
