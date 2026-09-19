#!/bin/bash
# Resumable, hash-checked downloads. Sourced by lib/common.sh, never executed directly.
# Needs only curl and shasum, so the first step can use it before Sniper's own Python exists.
# DOWNLOAD_QUIET=1 hides curl's per-file progress meter (for many small files, where the
# caller prints its own "[n/N]" line instead).

# fetch_part URL PART SHA256 — 0: PART is complete and correct; 1: it is complete
# but wrong; 2: the transfer stopped part-way (a connection problem; PART keeps what
# arrived); 3: the server refused to continue an existing PART (HTTP error, e.g. 416
# for a partial file longer than the real one) without adding a byte.
fetch_part() {
  local before=0 after=0 rc=0
  [ -f "$2" ] && before="$(stat -f %z "$2")"
  curl -fL ${DOWNLOAD_QUIET:+-sS} --retry 3 --retry-delay 2 -C - -o "$2" "$1" || rc=$?
  CURL_RC="$rc"
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
# TARGET only once its SHA-256 matches. A resumed partial file that proves wrong or
# cannot be resumed is discarded and fetched once more from the start, in the same
# run; a fresh download that is wrong is deleted and reported.
download_verified() {
  local url="$1" target="$2" want="$3" label="$4" part="$2.part" rc resumed=0
  if [ -f "$target" ] && [ "$(sha "$target")" = "$want" ]; then return 0; fi
  rm -f "$target"
  if [ -f "$part" ]; then resumed=1; say "Resuming $label from $(stat -f %z "$part") bytes."; else say "Downloading $label."; fi
  fetch_part "$url" "$part" "$want"; rc=$?
  if [ "$resumed" = 1 ] && { [ "$rc" = 1 ] || [ "$rc" = 3 ]; }; then
    rm -f "$part"; say "The partial download was not usable; downloading $label again from the beginning."
    fetch_part "$url" "$part" "$want"; rc=$?
  fi
  case "$rc" in
    0) mv "$part" "$target"; return 0 ;;
    2) if [ "$(stat -f %z "$part" 2>/dev/null || echo 0)" = 0 ]; then
         rm -f "$part"
         fail "Could not download $label: no connection to its server (curl error $CURL_RC).
  Check your internet connection, then run the installer again."
       fi
       fail "Downloading $label stopped before it finished (curl error $CURL_RC); the $(stat -f %z "$part")
  bytes received are kept. Run the installer again when your connection is stable; it resumes." ;;
  esac
  rm -f "$part"
  fail "Downloading $label produced the wrong file (checksum mismatch); it was deleted.
  Run the installer again to download it afresh."
}
