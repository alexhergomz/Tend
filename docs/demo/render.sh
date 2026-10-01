#!/usr/bin/env bash
# Rebuild the GIFs and screenshots in docs/ from real sessions of `t`.
set -euo pipefail
cd "$(dirname "$0")/../.."
AGG=${AGG:-agg}
TMP=$(mktemp -d)
python3 docs/demo/record.py "$TMP"
opts=(--font-family "DejaVu Sans Mono" --font-size 18 --idle-time-limit 3 --last-frame-duration 4)

last_frame() {  # cast, agg theme, output png
  "$AGG" -q "${opts[@]}" --theme "$2" "$TMP/$1.cast" "$TMP/$1.gif"
  mkdir -p "$TMP/frames-$1"
  ffmpeg -v error -i "$TMP/$1.gif" -fps_mode passthrough "$TMP/frames-$1/%03d.png"
  cp "$TMP/frames-$1/$(ls "$TMP/frames-$1" | tail -1)" "$3"
}

for n in capture interactive triage focus resolve review states repeat; do
  "$AGG" -q "${opts[@]}" --theme monokai "$TMP/$n.cast" "docs/$n.gif"
done
for n in queue plan gantt stats plugins doctor help; do
  last_frame "$n" monokai "docs/$n.png"
done
# the three themes side by side; the light one on a light terminal
last_frame theme-dark monokai "$TMP/a.png"
last_frame theme-light github-light "$TMP/b.png"
last_frame theme-plain monokai "$TMP/c.png"
convert "$TMP/a.png" "$TMP/b.png" "$TMP/c.png" -bordercolor "#1b1d23" -border 6 +append docs/themes.png
rm -rf "$TMP"
