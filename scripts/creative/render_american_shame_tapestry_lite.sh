#!/usr/bin/env bash
# Lite / Preview version of the American Shame Tapestry
# Much faster render, lower quality, good for quick iteration

set -euo pipefail

ASSET_DIR="./ash_assets"

AUDIO="${ASSET_DIR}/Geography of Ash.mp3"
BEAST="${ASSET_DIR}/grok-video-f7fb01e1-2c25-49fb-99a0-aa473c9e96a5.mp4"
BASE="${ASSET_DIR}/image.png"

OUTPUT="american_shame_tapestry_lite.mp4"

echo "=== Rendering American Shame Tapestry (LITE / Preview) ==="

ffmpeg -y \
  -i "$AUDIO" -i "$BEAST" -i "$BASE" \
  -filter_complex "
    [2:v]scale=1280:720,zoompan=z='min(zoom+0.001,1.6)':d=1:s=1280x720 [bg];
    [1:v]scale=640:360 [beast];
    [bg][beast]overlay=640:360:enable='between(t,300,414)' [v1];
    [0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo [aout]
  " \
  -map "[v1]" -map "[aout]" \
  -c:v libx264 -preset fast -crf 28 \
  -c:a aac -b:a 128k \
  -t 414 \
  -vf "eq=brightness=0.03:contrast=1.08" \
  "$OUTPUT"

echo ""
echo "✅ Lite render complete: $OUTPUT"
echo "This is a fast preview version (lower resolution/quality)."