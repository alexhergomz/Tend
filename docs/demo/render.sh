#!/usr/bin/env bash
# Rebuild the GIFs and screenshot in docs/ from real sessions of `t`.
set -euo pipefail
cd "$(dirname "$0")/../.."
AGG=${AGG:-agg}
TMP=$(mktemp -d)
python3 docs/demo/record.py "$TMP"
opts=(--font-family "DejaVu Sans Mono" --font-size 18 --theme monokai --idle-time-limit 3 --last-frame-duration 4)
for n in capture interactive triage focus resolve review states repeat; do
  "$AGG" -q "${opts[@]}" "$TMP/$n.cast" "docs/$n.gif"
done
# still images: the last frame of these sessions
for n in queue plan gantt stats plugins; do
  "$AGG" -q "${opts[@]}" "$TMP/$n.cast" "$TMP/$n.gif"
  mkdir "$TMP/frames-$n"
  ffmpeg -v error -i "$TMP/$n.gif" -fps_mode passthrough "$TMP/frames-$n/%03d.png"
  cp "$TMP/frames-$n/$(ls "$TMP/frames-$n" | tail -1)" "docs/$n.png"
done
rm -rf "$TMP"
