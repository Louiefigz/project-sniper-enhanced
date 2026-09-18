#!/bin/bash
# Project Sniper — preview and then remove only regenerable render caches.
# It never touches source footage, edit plans, approved finals, exports or
# unsynced Studio changes.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
say "Candidates (regenerable render caches only):"
TOTAL=0
for d in "$APP_DIR/templates/motion/.sniper-native-runtime"/*/frame-cache \
         "$APP_DIR/templates/motion/.sniper-native-runtime"/*/long-frame-cache; do
  [ -d "$d" ] || continue
  SZ="$(du -sh "$d" 2>/dev/null | cut -f1)"
  say "  $SZ  $d"
  TOTAL=$((TOTAL+1))
done
[ "$TOTAL" -gt 0 ] || { say "  (none)"; exit 0; }
say ""
say "NOT candidates, and never removed by this script: your footage, edit plans,"
say "final.mp4 files, exports, approval receipts and unsynced Studio edits."
printf 'Type CLEAN to remove the caches listed above: '
read -r answer
[ "$answer" = "CLEAN" ] || { say "Nothing was removed."; exit 0; }
for d in "$APP_DIR/templates/motion/.sniper-native-runtime"/*/frame-cache \
         "$APP_DIR/templates/motion/.sniper-native-runtime"/*/long-frame-cache; do
  [ -d "$d" ] && rm -rf "$d"
done
say "Caches removed. The next render rebuilds what it needs."
