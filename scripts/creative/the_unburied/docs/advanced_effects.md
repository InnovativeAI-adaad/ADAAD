# The Unburied — Advanced Effects Breakdown

**Project:** the_unburied (American Shame Tapestry series)  
**Status:** Polished small example registered through the governed creative workflow  
**Render:** `render_the_unburied.sh` (110s, crf 18, slower preset)

This piece demonstrates the full advanced creative pipeline in a compact, self-contained form. Every technique is reproducible via the Python generator + standalone Bash renderer.

## Core Stylistic Goals
- "Buried / Redacted" aesthetic: names and bodies deliberately obscured then violently revealed.
- Maximum digital + analog destruction on top of archival source.
- Kinetic text that feels like it is being dug up or scratched out.

## Techniques Deployed (Extreme / Stylized)

### 1. Per-Pass Chromatic Aberration + Film Destruction Grain
- `geq` expressions with high-frequency sin/cos on each RGB channel independently per major section.
- `noise=alls=52` base + additional layers during glitch windows.
- Heavy `eq` contrast/saturation crushing + gamma pushes toward "dirt in the lens" look.

### 2. Violent Multi-Stage Glitch / Datamosh Bursts
- Four-way split + timed `blend` (difference / addition / average) at staggered high frequencies (0.017s–0.041s periods).
- Overlapping enable windows create cascading corruption that feels like tape head clogs and packet loss.
- Dedicated "redaction overlay" (speech bubbles texture with extreme alpha) that appears only during the heaviest buried sections.

### 3. Extreme Multi-Layer Kinetic "Digging" Text
- Every major phrase has a primary high-amplitude sin/cos modulated layer.
- Secondary "ghost/tear" layer at much higher frequency, offset 2–3 px, low alpha, accent color (blood red, toxic green, archival gold).
- Text phrases timed to "emerge" from heavy glitch (THE UNBURIED, NAMES IN THE DIRT, THE GROUND REMEMBERS).
- One "redacted" block of pure black text that stutters during peak corruption.

### 4. Reveal Structure
- 0–38s   : Violent burial + name struggle (THE UNBURIED primary + ghost)
- 19–55s  : Redacted / black bar phase (NAMES suppressed)
- 52–88s  : Digging climax (NAMES IN THE DIRT dual kinetic layers)
- 89–108s : Final corrupted handoff + "THE GROUND REMEMBERS" sting

## How This Fits the Workflow
- Registered via `python scripts/creative/creative_output.py --action register --project the_unburied`
- Advanced mode supported in `the_unburied_pipeline.py`
- Self-contained render script (no external complex dependencies beyond the shared ash_assets)
- Manifest + ledger entry generated on every iteration
- Can be invoked the same way as Geography of Ash pieces

## Reproduction
```bash
cd scripts/creative/the_unburied
./render_the_unburied.sh
```

Or through the central dispatcher:
```bash
python ../../creative_output.py --project the_unburied --action generate --mode advanced
```

This small example proves the register + advanced pipeline pattern scales cleanly to new pieces without losing governance hygiene.

---
*Part of ADAAD Epoch A creative output layer — evidence, reproducibility, and maximum stylized aggression.*