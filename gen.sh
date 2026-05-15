#!/usr/bin/env bash
set -euo pipefail

ARCHIVE_DIR="${1:-gallery-dl/twitter/suganami_mirei}"
OUTPUT_HTML="${2:-output/suganami_mirei/timeline.html}"

mkdir -p "$(dirname "$OUTPUT_HTML")"

cmd=(python3 build_twitter_archive.py "$ARCHIVE_DIR" -o "$OUTPUT_HTML")

if [[ -n "${MEDIA_BASE_URL:-}" ]]; then
  cmd+=(--media-base-url "$MEDIA_BASE_URL")
fi

"${cmd[@]}"
