#!/usr/bin/env bash
# =============================================================================
# "Resistance Index" — American Shame Tapestry (Next Piece)
# Registered via creative_output.py --action register
# Hyper-stylized digital ledger / index corruption piece.
# Typewriter-jam text, vertical roll glitches, data-tear list destruction,
# counting names that get erased in real time, extreme index motif.
# =============================================================================

set -euo pipefail

ASSET_DIR="./ash_assets"
AUDIO="${ASSET_DIR}/Geography of Ash.mp3"
BASE="${ASSET_DIR}/image.png"
OVERLAY="${ASSET_DIR}/speech_bubbles_overlay.png"

OUTPUT="resistance_index_advanced.mp4"

echo "=== Rendering Resistance Index (HYPER-STYLIZED / LEDGER CORRUPTION) ==="

ffmpeg -y \
  -i "$AUDIO" -i "$BASE" -i "$OVERLAY" \
  -filter_complex "
    [1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,
         zoompan=z='min(zoom+0.0006,1.72)':d=1:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=1920x1080,
         eq=brightness=-0.18:contrast=1.55:saturation=0.32:gamma=1.22,
         noise=alls=44:alls_seed=29,
         geq='r=r(t+sin(t*7.3)*2.9):g=g(t+cos(t*5.4)*3.6):b=b(t+sin(t*4.1)*2.2)' [core];

    [2:v]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.12 [data];

    # Data index corruption engine (vertical roll + list tearing)
    [core]split=5 [c1][c2][c3][c4][c5];
    [c1][c2]blend=all_mode=difference:all_opacity='if(between(mod(t,0.019),0.0,0.009),0.85,0.12)':enable='between(t,12,29)' [roll1];
    [roll1][c3]blend=all_mode=addition:all_opacity='if(between(mod(t,0.026),0.0,0.012),0.67,0.08)':enable='between(t,28,51)' [tear1];
    [tear1][c4]blend=all_mode=average:all_opacity='if(between(mod(t,0.014),0.0,0.007),0.91,0.15)':enable='between(t,50,74)' [roll2];
    [roll2][c5]blend=all_mode=difference:all_opacity='if(between(mod(t,0.031),0.0,0.015),0.78,0.19)':enable='between(t,73,96)' [index_glitch];

    [index_glitch][data]overlay=0:0:enable='between(t,8,98)' [ledger];

    # Final index wipe / total corruption
    [ledger]split [l1][l2];
    [l1][l2]blend=all_mode=addition:all_opacity=0.48:enable='between(t,95,102)' [final_corrupt];

    [0:a]aformat=sample_fmts=fltp:sample_rates=44100 [aout]
  " \
  -map "[final_corrupt]" -map "[aout]" \
  -c:v libx264 -preset slower -crf 17 -pix_fmt yuv420p \
  -c:a aac -b:a 256k \
  -t 105 \
  -vf "
    eq=brightness=0.03:contrast=1.11:saturation=0.76,
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='RESISTANCE INDEX':fontcolor=#E8D5A3:fontsize=64:x=(w-text_w)/2+sin(t*6.8)*29:y=92+cos(t*5.9)*16:enable='between(t,3,34)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='RESISTANCE INDEX':fontcolor=#FF3311:fontsize=64:x=(w-text_w)/2+sin(t*11.4)*11+1:y=92+cos(t*8.7)*7:alpha=0.31:enable='between(t,3,34)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='NO.  1847  —  ELIZABETH  C.':fontcolor=#AACCBB:fontsize=28:x=140+sin(t*4.2)*6:y=210+cos(t*3.1)*4:enable='between(t,11,27)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='NO.  1848  —  THOMAS  R.':fontcolor=#AACCBB:fontsize=28:x=140+sin(t*4.7)*5:y=248+cos(t*3.6)*3:enable='between(t,13,29)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='NO.  1849  —  [REDACTED]':fontcolor=#662222:fontsize=28:x=140+cos(t*5.1)*8:y=286+sin(t*2.9)*5:enable='between(t,16,32)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='THE LEDGER IS A LIE':fontcolor=#FFEE66:fontsize=52:x=(w-text_w)/2+sin(t*7.9)*21:y=410:enable='between(t,31,58)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='THE LEDGER IS A LIE':fontcolor=#33FF99:fontsize=52:x=(w-text_w)/2+sin(t*13.6)*8-2:y=410+cos(t*9.2)*4:alpha=0.26:enable='between(t,31,58)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='COUNTING  THE  DISAPPEARED':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=520+sin(t*4.8)*9:enable='between(t,47,71)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='NO NAMES  —  NO  NUMBERS  —  NO  RECORD':fontcolor=#00DDAA:fontsize=31:x=(w-text_w)/2:y=620+cos(t*3.7)*7:enable='between(t,69,94)',
    drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:text='THE INDEX  REMEMBERS':fontcolor=#C5A13B:fontsize=48:x=(w-text_w)/2:y=h-180:enable='between(t,93,104)'
  " \
  "$OUTPUT"

echo ""
echo "✅ Resistance Index (advanced) complete: $OUTPUT"
echo "Features: Index/ledger motif, typewriter list corruption, vertical roll + data tear glitches, dual-layer counting text, total record erasure climax"