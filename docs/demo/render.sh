#!/usr/bin/env bash
# Rebuild the GIFs and screenshot in docs/ from real sessions of `t`.
set -euo pipefail
cd "$(dirname "$0")/../.."
AGG=${AGG:-agg}
TMP=$(mktemp -d)
python3 docs/demo/record.py "$TMP"
opts=(--font-family "DejaVu Sans Mono" --font-size 18 --theme monokai --idle-time-limit 3 --last-frame-duration 4)
for n in capture interactive triage focus resolve; do
  "$AGG" -q "${opts[@]}" "$TMP/$n.cast" "docs/$n.gif"
done
"$AGG" -q "${opts[@]}" "$TMP/queue.cast" "$TMP/queue.gif"
mkdir "$TMP/frames"
ffmpeg -v error -i "$TMP/queue.gif" -fps_mode passthrough "$TMP/frames/%03d.png"
cp "$TMP/frames/$(ls "$TMP/frames" | tail -1)" docs/queue.png
rm -rf "$TMP"
