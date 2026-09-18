#!/bin/bash
# Project Sniper — Mac installer.
#
#   install/install.command [--provider codex|claude]
#
# Installs what Sniper needs inside this folder: the app's dependencies and
# Python environment under app/, and the rendering browser, speech model and
# pinned provider CLIs under runtime/. It does not change your own Node, Python,
# Homebrew, Codex or Claude installation, or your existing Codex/Claude login.
#
# Safe to run again. Each step records what it finished with; a step is redone
# when its inputs changed or it never finished, and skipped only when its
# receipt matches. Your settings in runtime/sniper.local.env are never touched.

. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1

PROVIDER_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDER_ARG="${2:-}"; shift 2 ;;
    *) fail "Unknown option: $1  (usage: install.command [--provider codex|claude])" ;;
  esac
done

require_macos
require_safe_install_path
mkdir -p "$RUNTIME_DIR" "$STATE_DIR" "$RECEIPTS" "$LOG_DIR"
log_line "install started"
# The Python environment and the app build record the folder they were made in.
# If this folder was moved or copied since, redo exactly those two steps.
if [ -f "$RECEIPTS/location" ] && ! receipt_ok location "$PKG_ROOT"; then
  say "This folder was moved or copied since it was installed; redoing the steps that record its location."
  clear_receipt venv; clear_receipt build; rm -rf "$APP_DIR/.venv"
fi
write_receipt location "$PKG_ROOT"
RELEASE_JSON="$PKG_ROOT/RELEASE.json"
pin() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['components'][sys.argv[2]])" "$RELEASE_JSON" "$1"; }

say "Project Sniper installer — $PKG_ROOT"

# ---------------------------------------------------------------- 1. prerequisites
step "1/10  Checking the tools you install yourself"
HAVE_BREW=1; command -v brew >/dev/null 2>&1 || HAVE_BREW=0
brew_hint() {
  if [ "$HAVE_BREW" = 1 ]; then say "  Install it with:   brew install $1"
  else say "  Homebrew is not installed. Either install Homebrew from https://brew.sh and run
  'brew install $1', or install $1 another way and make sure it is on your PATH."; fi
}
MAJOR="$(node_major)"
if [ -z "$MAJOR" ] || [ "$MAJOR" -lt 22 ] 2>/dev/null; then
  say "Node 22 or newer is required; found: $(node --version 2>/dev/null || echo none)."
  say "  Download the LTS version from https://nodejs.org (Node 24 is recommended)."
  fail "Node is missing or too old."
fi
[ "$MAJOR" -ge 24 ] 2>/dev/null || [ "$MAJOR" -eq 22 ] 2>/dev/null \
  || warn "Node $(node --version) is not an LTS release; Node 24 is recommended."
say "Node $(node --version) — ok"

PYTHON_BIN="$(find_python)" || {
  say "Python 3.12 or newer is required (numpy and scipy in this release need 3.12)."
  say "  Download it from https://www.python.org/downloads/macos/"
  fail "Python 3.12+ is missing."; }
PY_VER="$("$PYTHON_BIN" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
say "Python $PY_VER — ok (this release was tested with 3.14.4)"

for tool in ffmpeg ffprobe whisper-cli; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    say "$tool is required and was not found."
    case "$tool" in whisper-cli) brew_hint whisper-cpp ;; *) brew_hint ffmpeg ;; esac
    fail "$tool is missing."
  fi
done
MISSING="$(ffmpeg_missing_features "$(command -v ffmpeg)")"
if [ -n "$MISSING" ]; then
  say "Your ffmpeg ($(command -v ffmpeg)) lacks features the renderer uses: $MISSING"
  say "  The Homebrew build includes them. Other builds must be configured with"
  say "  libass, libfreetype, librubberband, libzimg and libx264."
  fail "ffmpeg is missing required features."
fi
say "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}') with every required filter — ok"
say "whisper-cli — ok"

# ------------------------------------------------------- 2-3. app dependencies
npm_root() {  # label dir receipt-name
  local key="node-$(node --version)|lock-$(sha "$2/package-lock.json")"
  if receipt_ok "$3" "$key" && [ -d "$2/node_modules" ]; then say "$1 — up to date"; return 0; fi
  clear_receipt "$3"
  # Remove whatever an earlier, interrupted attempt left behind before reinstalling.
  # npm ci alone can fail on a half-extracted tree (seen in the interruption test:
  # ENOENT on chmod inside a partially written package).
  rm -rf "$2/node_modules"
  ( cd "$2" && npm ci --no-audit --no-fund ) || fail "Installing $1 failed.
  Check your connection and run the installer again; it repeats this step."
  write_receipt "$3" "$key"; say "$1 — installed"
}
step "2/10  Application dependencies"
npm_root "app dependencies" "$APP_DIR" npm-app
step "3/10  Rendering-project dependencies"
npm_root "rendering-project dependencies" "$APP_DIR/templates/motion" npm-motion

# ------------------------------------------------------------ 4. python
step "4/10  Python environment from the pinned list"
LOCK="$PKG_ROOT/install/requirements.lock.txt"
PYKEY="python-$PY_VER|lock-$(sha "$LOCK")"
if receipt_ok venv "$PYKEY" && [ -x "$APP_DIR/.venv/bin/python3" ]; then
  say "Python environment — up to date"
else
  clear_receipt venv
  rm -rf "$APP_DIR/.venv"   # rebuild from scratch: a partial venv is never reused
  "$PYTHON_BIN" -m venv "$APP_DIR/.venv" || fail "Could not create the Python environment."
  "$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q -r "$LOCK" \
    || fail "Installing the pinned Python packages failed. Run the installer again."
  write_receipt venv "$PYKEY"; say "Python environment — installed"
fi

# ------------------------------------------------------------ 5. browser
step "5/10  Rendering browser"
CHROME_PIN="$(pin chrome_headless_shell)"
find_browser() { ls -d "$BROWSER_CACHE"/chrome-headless-shell/*"$CHROME_PIN"*/*/chrome-headless-shell 2>/dev/null | head -1; }
BROWSER_BIN="$(find_browser)"
if receipt_ok browser "$CHROME_PIN" && [ -x "$BROWSER_BIN" ] && "$BROWSER_BIN" --version >/dev/null 2>&1; then
  say "chrome-headless-shell $CHROME_PIN — up to date"
else
  clear_receipt browser
  say "Downloading chrome-headless-shell $CHROME_PIN (about 90 MB)..."
  ( cd "$APP_DIR/templates/motion" && npx --no-install @puppeteer/browsers install \
      "chrome-headless-shell@$CHROME_PIN" --path "$BROWSER_CACHE" ) >> "$LOG_DIR/install.log" 2>&1 \
    || fail "Downloading the rendering browser failed. Run the installer again when
  your connection is stable. Rendering never downloads a browser on its own."
  BROWSER_BIN="$(find_browser)"
  [ -x "$BROWSER_BIN" ] && "$BROWSER_BIN" --version >/dev/null 2>&1 \
    || fail "The rendering browser did not install correctly."
  write_receipt browser "$CHROME_PIN"; say "chrome-headless-shell $CHROME_PIN — installed"
fi

# ------------------------------------------------------------ 6. speech model
step "6/10  Speech model"
MODEL_NAME="ggml-small.en.bin"
MODEL_PATH="$WHISPER_DIR/$MODEL_NAME"
MODEL_SHA="c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"
MODEL_URL="${SNIPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL_NAME}"
mkdir -p "$WHISPER_DIR"
# No model file means no completed step, whatever an earlier run recorded.
[ -f "$MODEL_PATH" ] || clear_receipt model
if [ ! -f "$MODEL_PATH" ]; then
  # Reuse an identical copy already on this Mac (verified by hash, cloned on APFS).
  for existing in "$HOME/.cache/hyperframes/whisper/models/$MODEL_NAME" \
                  "/opt/homebrew/share/whisper-cpp/models/$MODEL_NAME" \
                  "/usr/local/share/whisper-cpp/models/$MODEL_NAME"; do
    if [ -f "$existing" ] && [ "$(sha "$existing")" = "$MODEL_SHA" ]; then
      cp -c "$existing" "$MODEL_PATH" 2>/dev/null || cp "$existing" "$MODEL_PATH"
      say "Found an identical speech model already on this Mac; reused it."; break
    fi
  done
fi
if [ ! -f "$MODEL_PATH" ]; then
  say "Downloading the speech model (about 465 MB). An interrupted download resumes."
  curl -fL --retry 3 --retry-delay 2 -C - -o "$MODEL_PATH.part" "$MODEL_URL" \
    || fail "Downloading the speech model failed. Run the installer again — it resumes
  from where it stopped. Or download $MODEL_NAME from
  https://huggingface.co/ggerganov/whisper.cpp and save it as $MODEL_PATH"
  if [ "$(sha "$MODEL_PATH.part")" != "$MODEL_SHA" ]; then
    rm -f "$MODEL_PATH.part"
    fail "The downloaded speech model is not the expected file (checksum mismatch).
  It was deleted. Run the installer again to download it afresh."
  fi
  mv "$MODEL_PATH.part" "$MODEL_PATH"
fi
if [ "$(sha "$MODEL_PATH")" != "$MODEL_SHA" ]; then
  clear_receipt model
  fail "The speech model at $MODEL_PATH does not match the expected checksum.
  Delete that file and run the installer again."
fi
write_receipt model "$MODEL_SHA"; say "Speech model verified"

# ------------------------------------------------------------ 7. provider CLIs
step "7/10  Pinned Codex and Claude CLIs (kept inside this folder)"
CODEX_WANT="$(pin codex_cli_admitted)"; CLAUDE_WANT="$(pin claude_cli_admitted)"
mkdir -p "$CLAUDE_CONFIG_DIR_LOCAL" "$CODEX_HOME_LOCAL"; chmod 700 "$CLAUDE_CONFIG_DIR_LOCAL" "$CODEX_HOME_LOCAL"
# Even --version makes the Codex CLI write into its home folder: point it at
# Sniper's own, never at yours.
cli_ok() { [ -x "$CLI_BIN/$1" ] && [ "$(CODEX_HOME="$CODEX_HOME_LOCAL" CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR_LOCAL" \
  "$CLI_BIN/$1" --version 2>/dev/null | head -1)" = "$2" ]; }
if receipt_ok cli "$CODEX_WANT|$CLAUDE_WANT" && cli_ok codex "$CODEX_WANT" && cli_ok claude "$CLAUDE_WANT"; then
  say "Codex and Claude CLIs — up to date"
else
  clear_receipt cli
  mkdir -p "$CLI_PREFIX"
  npm install --prefix "$CLI_PREFIX" --no-audit --no-fund --silent \
      "@openai/codex@${CODEX_WANT##* }" "@anthropic-ai/claude-code@${CLAUDE_WANT%% *}" \
    || fail "Installing the pinned CLIs failed. Run the installer again."
  cli_ok codex "$CODEX_WANT" || fail "The Codex CLI does not report '$CODEX_WANT'."
  cli_ok claude "$CLAUDE_WANT" || fail "The Claude CLI does not report '$CLAUDE_WANT'."
  write_receipt cli "$CODEX_WANT|$CLAUDE_WANT"; say "Codex and Claude CLIs — installed"
fi

# ------------------------------------------------------------ 8. configuration
step "8/10  Configuration"
PROVIDER="$(env_value SNIPER_PROVIDER)"
[ -n "$PROVIDER_ARG" ] && PROVIDER="$PROVIDER_ARG"
if [ -z "$PROVIDER" ] && [ -t 0 ]; then
  say "Which subscription will Sniper use to plan edits?"
  say "  1) Codex (ChatGPT subscription)   2) Claude (Claude subscription)"
  printf 'Choose 1 or 2: '; read -r choice
  case "$choice" in 1) PROVIDER=codex ;; 2) PROVIDER=claude ;; esac
fi
case "$PROVIDER" in
  codex) BRAIN=codex ;; claude) BRAIN=legacy ;;
  *) fail "Choose a provider: run install/install.command --provider codex  (or claude)." ;;
esac
WORKSPACE="$(env_value SNIPER_WORKSPACE_ROOT)"; WORKSPACE="${WORKSPACE:-$HOME/ProjectSniper}"
mkdir -p "$WORKSPACE" || fail "Cannot create the video workspace at $WORKSPACE"
cat > "$ENV_FILE.tmp" <<ENVEOF
# Written by install.command; regenerated on every install. Put your own
# settings in runtime/sniper.local.env, which the installer never changes.
PKG_ROOT="$PKG_ROOT"
APP_DIR="$APP_DIR"
PATH="$CLI_BIN:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SNIPER_PROVIDER="$PROVIDER"
SNIPER_BRAIN_PROVIDER="$BRAIN"
SNIPER_EXECUTION_MODE="local"
SNIPER_WORKSPACE_ROOT="$WORKSPACE"
SNIPER_NODE_PATH="$(command -v node)"
HYPERFRAMES_BROWSER_PATH="$BROWSER_BIN"
HYPERFRAMES_FFMPEG_PATH="$(command -v ffmpeg)"
HYPERFRAMES_FFPROBE_PATH="$(command -v ffprobe)"
HYPERFRAMES_NO_TELEMETRY="1"
NEXT_TELEMETRY_DISABLED="1"
HYPERFRAMES_NO_UPDATE_CHECK="1"
HYPERFRAMES_NO_AUTO_INSTALL="1"
WHISPER_CPP_BIN="$(command -v whisper-cli)"
WHISPER_CPP_MODEL="$MODEL_PATH"
SNIPER_TRANSCRIBE_PROVIDER="local-whisper"
SNIPER_CODEX_BIN="codex"
CLAUDE_BIN="claude"
CODEX_HOME="$CODEX_HOME_LOCAL"
CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR_LOCAL"
DISABLE_AUTOUPDATER="1"
SNIPER_PORT="$PORT"
ENVEOF
mv "$ENV_FILE.tmp" "$ENV_FILE"; chmod 600 "$ENV_FILE"
[ -f "$APP_DIR/.env.local" ] || cp "$APP_DIR/.env.local.example" "$APP_DIR/.env.local"
say "Editor brain: $PROVIDER   ·   Video projects: $WORKSPACE"

# ------------------------------------------------------------ 9. render runtime
step "9/10  Rendering runtime"
# native_runtime.py refuses to overwrite a half-built runtime ('installing/'), by
# design. The installer is its only writer while installing: if nothing has a file
# open there and no finished runtime sits beside it, it is left from an interrupted
# run and is removed so this step can be redone.
for staging in "$APP_DIR"/templates/motion/.sniper-native-runtime/*/installing; do
  [ -d "$staging" ] || continue
  [ -d "$(dirname "$staging")/hyperframes" ] && continue
  [ -z "$(lsof +D "$staging" 2>/dev/null | awk 'NR>1')" ] || fail "A rendering runtime is being built by another process ($staging). Wait for it, then run the installer again."
  rm -rf "$staging"; say "Removed an unfinished rendering runtime left by an interrupted run."
done
( load_env; cd "$APP_DIR" && PYTHONPATH="$APP_DIR/scripts/producer" "$APP_DIR/.venv/bin/python3" \
    "$APP_DIR/scripts/producer/studio/native_runtime.py" >/dev/null ) \
  || fail "The rendering runtime did not build from its shipped patch set."
say "Rendering runtime — verified"

# ------------------------------------------------------------ 10. production app
step "10/10  Building the app (no network needed)"
BUILDKEY="$(python3 -c "import json;print(json.load(open('$RELEASE_JSON'))['version'])")|node-$(node --version)"
if receipt_ok build "$BUILDKEY" && [ -f "$APP_DIR/.next/BUILD_ID" ]; then
  say "App build — up to date"
else
  clear_receipt build
  if ! ( load_env; cd "$APP_DIR" && npm run build ) >> "$LOG_DIR/build.log" 2>&1; then
    tail -15 "$LOG_DIR/build.log" >&2
    fail "Building the app failed (the lines above are from $LOG_DIR/build.log).
  Run the installer again; if it fails the same way, run install/diagnostics.command."
  fi
  [ -f "$APP_DIR/.next/BUILD_ID" ] || fail "The app build finished without a build id."
  write_receipt build "$BUILDKEY"; say "App build — done ($(cat "$APP_DIR/.next/BUILD_ID"))"
fi
log_line "install finished"

say ""
"$PKG_ROOT/install/doctor.command"
DOCTOR=$?
say ""
if [ "$DOCTOR" -ne 0 ]; then
  say "Installed, but the checks above report something still to do."
  say "If the only failure is the editor brain, sign in next:"
fi
say "  install/sign-in.command         (signs in to $PROVIDER inside this folder)"
say "Then open START-HERE.html."
exit "$DOCTOR"
