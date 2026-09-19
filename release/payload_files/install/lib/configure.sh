#!/bin/bash
# The installer's configuration step: which provider, and the settings file.
# Sourced by install/install.command (and by the installer tests, which call these
# exact functions), never executed directly. Expects the variables the earlier
# steps set: DEPS_PREFIX, NODE_BIN, TOOL_*, BROWSER_BIN, MODEL_PATH, PROVIDER_ARG, WORKSPACE_ARG.

choose_provider() {
  PROVIDER="$(settings_value SNIPER_PROVIDER)"
  [ -n "$PROVIDER_ARG" ] && PROVIDER="$PROVIDER_ARG"
  if [ -z "$PROVIDER" ] && [ -t 0 ]; then
    say "Which subscription will Sniper use to plan edits?"
    say "  1) Codex (ChatGPT subscription)   2) Claude (Claude subscription)"
    printf 'Choose 1 or 2 [1]: '; read -r choice
    case "$choice" in ''|1) PROVIDER=codex ;; 2) PROVIDER=claude ;; esac
  fi
  BRAIN="$(brain_for_provider "$PROVIDER")" \
    || fail "Choose a provider: run install/install.command --provider codex  (or claude)."
}

write_settings() {
  local workspace
  workspace="${WORKSPACE_ARG:-$(settings_value SNIPER_WORKSPACE_ROOT)}"; workspace="${workspace:-$HOME/ProjectSniper}"
  case "$workspace" in /*) ;; *) fail "The video workspace must be an absolute folder path: $workspace" ;; esac
  mkdir -p "$workspace" || fail "Cannot create the video workspace at $workspace"
  settings_write "$ENV_FILE" \
    "PKG_ROOT=$PKG_ROOT" "APP_DIR=$APP_DIR" \
    "PATH=$RUNTIME_BIN:$CLI_BIN:$DEPS_PREFIX/bin:/usr/bin:/bin:/usr/sbin:/sbin" "SNIPER_DEPS_PREFIX=$DEPS_PREFIX" \
    "SNIPER_PROVIDER=$PROVIDER" "SNIPER_BRAIN_PROVIDER=$BRAIN" \
    "SNIPER_CLAUDE_MODEL=$(release_value components.claude_model_default)" \
    "SNIPER_CODEX_MODEL=$(release_value components.codex_model_default)" \
    "SNIPER_CODEX_REASONING=$(release_value components.codex_reasoning_default)" \
    "SNIPER_EXECUTION_MODE=local" "SNIPER_WORKSPACE_ROOT=$workspace" \
    "SNIPER_NODE_PATH=$NODE_BIN" "HYPERFRAMES_BROWSER_PATH=$BROWSER_BIN" \
    "HYPERFRAMES_FFMPEG_PATH=$TOOL_FFMPEG" "HYPERFRAMES_FFPROBE_PATH=$TOOL_FFPROBE" \
    "HYPERFRAMES_NO_TELEMETRY=1" "NEXT_TELEMETRY_DISABLED=1" \
    "HYPERFRAMES_NO_UPDATE_CHECK=1" "HYPERFRAMES_NO_AUTO_INSTALL=1" \
    "WHISPER_CPP_BIN=$TOOL_WHISPER_CLI" "WHISPER_CPP_MODEL=$MODEL_PATH" \
    "SNIPER_TRANSCRIBE_PROVIDER=local-whisper" "SNIPER_CODEX_BIN=codex" "CLAUDE_BIN=claude" \
    "CODEX_HOME=$CODEX_HOME_LOCAL" "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR_LOCAL" \
    "DISABLE_AUTOUPDATER=1" "SNIPER_PORT=$PORT"
  SNIPER_WORKSPACE_ROOT="$workspace"
}

# The settings just written must load back exactly (the loader, not the writer,
# is what every launcher uses), and their PATH must find Sniper's own tools first.
verify_settings() {
  local workspace tool found
  workspace="$(settings_load "$ENV_FILE" && printf '%s' "$SNIPER_WORKSPACE_ROOT")" || fail "The settings just written do not load."
  [ "$workspace" = "$SNIPER_WORKSPACE_ROOT" ] || fail "The settings did not read back exactly. Please report this."
  for tool in node ffmpeg ffprobe whisper-cli tesseract yt-dlp; do
    found="$(settings_load "$ENV_FILE" && command -v "$tool")"
    [ "$found" = "$RUNTIME_BIN/$tool" ] || fail "The settings' PATH finds $tool at '$found', not Sniper's own. Please report this."
  done
  for tool in python3 git npm; do
    found="$(settings_load "$ENV_FILE" && command -v "$tool")"
    [ "$found" = "$DEPS_PREFIX/bin/$tool" ] || fail "The settings' PATH finds $tool at '$found', not Sniper's own. Please report this."
  done
}
