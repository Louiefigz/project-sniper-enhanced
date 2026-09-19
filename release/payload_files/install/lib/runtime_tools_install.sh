#!/bin/bash
# Installs Sniper's own tools into ~/.project-sniper/runtimes/<lock id>/ (lib/runtime_tools.sh).
# Run by ensure_runtime_tools under an exclusive lockf lock on that folder, never directly.
# Needs only macOS's own bash, curl, tar, shasum and codesign: Sniper's Python arrives here.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh" || exit 1

TOOLS_LOG="$LOG_DIR/runtime-tools.log"
PKGS="$DEPS_HOME/pkgs"

lock_rows() {  # kind... — the lock rows of those kinds
  local kinds=" $* " kind sha bytes path source
  while read -r kind sha bytes path source; do
    case "$kind" in '#'*|'') continue ;; esac
    case "$kinds" in *" $kind "*) printf '%s %s %s %s %s\n' "$kind" "$sha" "$bytes" "$path" "$source" ;; esac
  done < "$DEPS_LOCK"
}

# Every package archive, resumable and checked (SNIPER_TOOLS_BASE_URL serves the same paths from
# a mirror; the installer tests use one).
download_all() {
  local kind sha bytes path source n=0 total url
  total="$(lock_rows micromamba conda | wc -l | tr -d ' ')"
  say "Downloading Sniper's tools: $total files, each checked against its SHA-256."
  while read -r kind sha bytes path source; do
    n=$((n + 1))
    url="${SNIPER_TOOLS_BASE_URL:+$SNIPER_TOOLS_BASE_URL/$path}"; url="${url:-$source}"
    mkdir -p "$PKGS/$(dirname "$path")"
    DOWNLOAD_QUIET=1 download_verified "$url" "$PKGS/$path" "$sha" \
      "[$n/$total] $(basename "$path") ($(( (bytes + 524288) / 1048576 )) MB)"
  done < <(lock_rows micromamba conda)
}

# micromamba from its checked archive; its binary must match the lock too.
extract_micromamba() {
  local archive bin_sha dir
  archive="$PKGS/$(lock_rows micromamba | awk '{print $4}')"
  bin_sha="$(lock_rows micromamba-bin | awk '{print $2}')"
  dir="$DEPS_HOME/tools/$(basename "$archive" .tar.bz2)"
  MICROMAMBA="$dir/bin/micromamba"
  [ -x "$MICROMAMBA" ] && [ "$(sha "$MICROMAMBA")" = "$bin_sha" ] && return 0
  rm -rf "$dir" "$dir.extracting" && mkdir -p "$dir.extracting" || fail "Cannot create $dir"
  tar -xjf "$archive" -C "$dir.extracting" bin/micromamba || fail "Unpacking micromamba failed. Run the installer again."
  [ "$(sha "$dir.extracting/bin/micromamba")" = "$bin_sha" ] || fail "micromamba does not match its pinned SHA-256."
  mv "$dir.extracting" "$dir"
}

# Offline, from the checked archives only, with micromamba's settings kept in ~/.project-sniper
# (never ~/.conda or ~/.mamba). --platform lets it re-sign what it relocates on Apple silicon.
create_prefix() {
  local explicit="$DEPS_HOME/runtimes/$DEPS_ID.explicit.txt"
  { printf '@EXPLICIT\n'; lock_rows conda | awk -v pkgs="$PKGS" '{print "file://" pkgs "/" $4 "#sha256:" $2}'; } > "$explicit"
  rm -rf "$DEPS_PREFIX"   # no completion marker: whatever is here is unfinished
  say "Installing Sniper's tools (offline, from the checked downloads)."
  env -i HOME="$DEPS_HOME/mamba-home" PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=C \
      MAMBA_ROOT_PREFIX="$DEPS_HOME/mamba-root" \
    "$MICROMAMBA" create --no-rc -y -q -p "$DEPS_PREFIX" --offline --platform osx-arm64 --always-copy \
      --file "$explicit" >> "$TOOLS_LOG" 2>&1 \
    || fail "Installing Sniper's tools failed (details: $TOOLS_LOG). Run the installer again."
  rm -rf "$DEPS_HOME/mamba-root/pkgs"   # unpacked copies; the checked archives stay in pkgs/
}

# Sniper's ffmpeg, shipped in this package: checked, then unpacked through a pipe so it is
# installed the way the downloaded tools are (owner decision 2026-09-18; not notarized yet).
add_ffmpeg() {
  local sha path
  read -r _ sha _ path _ < <(lock_rows local)
  [ "$(sha "$PKG_ROOT/install/deps/$path")" = "$sha" ] \
    || fail "install/deps/$path does not match its pinned SHA-256; this folder is damaged. Download Sniper again."
  /bin/cat "$PKG_ROOT/install/deps/$path" | tar -xJf - -C "$DEPS_PREFIX" \
    || fail "Unpacking Sniper's ffmpeg failed. Run the installer again."
}

# Apple silicon runs nothing whose signature a relocation broke; catch that here, not mid-edit.
check_signatures() {
  local file bad=0
  while IFS= read -r file; do
    case "$(head -c 4 "$file" | od -An -tx1 | tr -d ' \n')" in
      cffaedfe|cafebabe) codesign -v "$file" 2>/dev/null || bad=$((bad + 1)) ;;
    esac
  done < <(find "$DEPS_PREFIX/bin" "$DEPS_PREFIX/lib" -type f \( -perm +111 -o -name '*.dylib' -o -name '*.so' \))
  [ "$bad" = 0 ] || fail "$bad of Sniper's tool files have a broken code signature; run the installer again."
}

deps_paths
deps_ready && exit 0   # another installer finished it while this one waited
mkdir -p "$PKGS" "$DEPS_HOME/tools" "$DEPS_HOME/mamba-home" "$LOG_DIR"
log_line "runtime tools $DEPS_ID: install started"
download_all
extract_micromamba
create_prefix
add_ffmpeg
check_signatures
deps_check_tools || fail "Sniper's tools do not run: $DEPS_TOOL_PROBLEM (details: $TOOLS_LOG)."
"$DEPS_PREFIX/bin/python3" -I -B "$INSTALL_TOOLS" tree-record "$DEPS_PREFIX" "$DEPS_RECORD" $(deps_tree_excludes) >/dev/null \
  || fail "Could not record Sniper's tools."
printf '%s' "$DEPS_ID" > "$DEPS_PREFIX/.sniper-runtime-complete"
log_line "runtime tools $DEPS_ID: installed"
say "Sniper's own tools — installed ($(deps_header tools))"
