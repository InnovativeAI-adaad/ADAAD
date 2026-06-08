# Resistance Index — Advanced Effects Breakdown

**Project:** resistance_index (American Shame Tapestry series)  
**Status:** Fully realized polished example registered through the governed workflow  
**Render:** `render_resistance_index.sh` (105s, crf 17)

This is the direct follow-on piece after `the_unburied`. It was created by first running the `register` command, then immediately building a complete hyper-stylized work on top of the scaffold.

## Thematic Core
"Resistance Index" treats the historical record itself as the material being destroyed. The piece is a corrupted digital + analog ledger of the disappeared and those who resisted. Names and numbers are typed, then violently overwritten, rolled, and erased in real time.

## New / Distinct Techniques (beyond previous pieces)

### 1. Typewriter / Monospace Ledger Aesthetic
- Uses `DejaVuSansMono` for authentic index/ledger look.
- Staggered "NO. 184x — NAME" lines that appear like a real-time database dump, then get individually corrupted and redacted.
- Text behaves like a physical typewriter jamming or a dot-matrix printer failing.

### 2. Vertical Roll + Data-Tear Glitch Engine (Fresh Variant)
- Multi-split blend chain specifically tuned for "vertical tape roll" + horizontal data tearing.
- Different timing windows and opacity curves than the main tapestry or the_unburied (0.014s–0.031s periods).
- Creates the feeling of an old CCTV or archival tape machine eating its own index.

### 3. Counting / Erasure Kinetic Text
- List items that literally count up (1847, 1848, 1849...) while being destroyed.
- "THE LEDGER IS A LIE" and "NO NAMES — NO NUMBERS — NO RECORD" use the dual-layer primary + ghost technique with mono font for maximum data-corruption readability.
- Final sting "THE INDEX REMEMBERS" lands after total visual erasure.

### 4. Motif-Specific Destruction
- The core image is treated as "the paper/soil the index is written on".
- Heavy use of redaction-style low-alpha overlays timed exactly to the name-erasure windows.
- Climax features a full "index wipe" where the entire visual field collapses into difference/addition noise.

## How It Demonstrates the Workflow
- Created via the exact `register` path the user requested.
- Immediately elevated to the same standard as Geography of Ash and the_unburied (own render script, advanced pipeline support, detailed docs, rich manifest, ledger entries).
- Proves the system scales: new project → full aggressive artistic output in < one session.

## Reproduction
```bash
cd scripts/creative/resistance_index
./render_resistance_index.sh
```

Via the central dispatcher:
```bash
python ../../creative_output.py --project resistance_index --action generate --mode advanced
python ../../creative_output.py --project resistance_index --action manifest
```

This piece, together with `the_unburied`, shows that the governed creative layer now supports rapid, high-quality, stylistically distinct expansions of the American Shame Tapestry series while maintaining perfect traceability.

---
*ADAAD Epoch A — every name that was taken, every record that was burned, is rebuilt here in corrupted light.*