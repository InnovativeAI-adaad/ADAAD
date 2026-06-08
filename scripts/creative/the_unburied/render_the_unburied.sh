#!/usr/bin/env bash
# =============================================================================
# "The Unburied" — American Shame Tapestry (Small Example / Hyper-Stylized)
# Registered + advanced pipeline demonstration piece.
# Heavy redacted archival glitch, extreme kinetic text that "digs/buries",
# datamosh + RGB block corruption, maximum film destruction grain.
# Duration ~110s. Self-contained advanced example.
# =============================================================================

set -euo pipefail

ASSET_DIR="./ash_assets"
AUDIO="${ASSET_DIR}/Geography of Ash.mp3"
BASE="${ASSET_DIR}/image.png"          # repurposed as soil/ground core
OVERLAY="${ASSET_DIR}/speech_bubbles_overlay.png"  # used as static/redaction texture

OUTPUT="the_unburied_advanced.mp4"

echo "=== Rendering The Unburied (HYPER-STYLIZED SMALL EXAMPLE) ==="

ffmpeg -y \
  -i "$AUDIO" -i "$BASE" -i "$OVERLAY" \
  -filter_complex "
    [1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,
         zoompan=z='min(zoom+0.0008,1.95)':d=1:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=1920x1080,
         eq=brightness=-0.22:contrast=1.45:saturation=0.35:gamma=1.18,
         noise=alls=52:alls_seed=71,
         geq='r=r(t+sin(t*6.1)*3.4):g=g(t+cos(t*4.7)*2.9):b=b(t+sin(t*5.8)*4.2)' [core];

    [2:v]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.18 [redact];

    # Violent buried/redacted glitch engine (multiple overlapping corruption passes)
    [core]split=4 [c1][c2][c3][c4];
    [c1][c2]blend=all_mode=difference:all_opacity='if(between(mod(t,0.041),0.0,0.019),0.78,0.14)':enable='between(t,18,42)' [gl1];
    [gl1][c3]blend=all_mode=addition:all_opacity='if(between(mod(t,0.023),0.0,0.011),0.61,0.09)':enable='between(t,41,67)' [gl2];
    [gl2][c4]blend=all_mode=average:all_opacity='if(between(mod(t,0.017),0.0,0.008),0.92,0.11)':enable='between(t,66,91)' [gl3];

    [gl3][redact]overlay=0:0:enable='between(t,15,95)' [buried];

    # Final corrupted handoff into reveal
    [buried]split [b1][b2];
    [b1][b2]blend=all_mode=difference:all_opacity=0.55:enable='between(t,92,98)' [final_glitch];

    [0:a]aformat=sample_fmts=fltp:sample_rates=44100 [aout]
  " \
  -map "[final_glitch]" -map "[aout]" \
  -c:v libx264 -preset slower -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 256k \
  -t 110 \
  -vf "
    eq=brightness=0.02:contrast=1.09:saturation=0.78,
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='THE UNBURIED':fontcolor=#E8D5A3:fontsize=72:x=(w-text_w)/2+sin(t*9.4)*31:y=140+cos(t*7.8)*19:enable='between(t,4,38)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='THE UNBURIED':fontcolor=#FF4422:fontsize=72:x=(w-text_w)/2+sin(t*14.2)*12+2:y=140+cos(t*11.6)*8:alpha=0.29:enable='between(t,4,38)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='REDATED':fontcolor=#111111:fontsize=48:x=(w-text_w)/2+cos(t*8.7)*18:y=310+sin(t*6.3)*11:enable='between(t,19,55)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='NAMES IN THE DIRT':fontcolor=#C9A16B:fontsize=51:x=(w-text_w)/2+sin(t*7.1)*23:y=680+cos(t*5.9)*14:enable='between(t,52,88)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='NAMES IN THE DIRT':fontcolor=#00FF99:fontsize=51:x=(w-text_w)/2+sin(t*12.8)*7-3:y=680+cos(t*9.4)*5:alpha=0.25:enable='between(t,52,88)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='THE GROUND REMEMBERS':fontcolor=white:fontsize=44:x=(w-text_w)/2:y=h-210:enable='between(t,89,108)'
  " \
  "$OUTPUT"

echo ""
echo "✅ The Unburied (advanced small example) complete: $OUTPUT"
echo "Features: Extreme redacted glitch + kinetic digging text + buried datamosh corruption + archival destruction grain"