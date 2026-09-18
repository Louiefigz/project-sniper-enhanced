#!/bin/bash
# Project Sniper — preview and remove only regenerable render caches.
# Refuses while anything is rendering or has a cache file open. Never touches
# footage, edit plans, approved finals, exports, receipts or unsynced Studio work.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
ROOT="$APP_DIR/templates/motion/.sniper-native-runtime"
CANDIDATES=()
for d in "$ROOT"/*/frame-cache "$ROOT"/*/long-frame-cache; do [ -d "$d" ] && CANDIDATES+=("$d"); done
if [ ${#CANDIDATES[@]} -eq 0 ]; then say "No render caches to remove."; exit 0; fi
# Active work check: a live Producer process from this install, or any process
# holding a file open inside the caches, means a render may depend on them.
ACTIVE="$(pgrep -f "$APP_DIR/scripts/producer" 2>/dev/null; pgrep -f "$APP_DIR/templates/motion" 2>/dev/null)"
OPEN="$(lsof +D "$ROOT" 2>/dev/null | awk 'NR>1 {print $2}' | sort -u)"
if [ -n "$ACTIVE$OPEN" ]; then
  fail "A render appears to be running (process ids: $(echo $ACTIVE $OPEN)). Nothing was
  removed. Run this again when it has finished."
fi
say "Candidates (regenerable render caches only):"
for d in "${CANDIDATES[@]}"; do say "  $(du -sh "$d" 2>/dev/null | cut -f1)  $d"; done
say ""
say "Never removed by this script: your footage, edit plans, final.mp4 files,"
say "exports, approval receipts and unsynced Studio edits."
if [ "${1:-}" != "--yes" ]; then printf 'Type CLEAN to remove the caches listed above: '; read -r answer
  [ "$answer" = "CLEAN" ] || { say "Nothing was removed."; exit 0; }; fi
for d in "${CANDIDATES[@]}"; do rm -rf "$d"; done
say "Caches removed. The next render rebuilds what it needs."
