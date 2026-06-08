# ADAAD Creative Output Workflow

**Status:** Governed  
**Version:** 1.2  
**Last Updated:** 2026-05-28 (resistance_index fully realized as next complete example)

## Philosophy

Creative work produced inside the ADAAD system (video, audio, visual art, writing, etc.) is treated with the same seriousness as code or governance changes.

All creative outputs should be:

- Reproducible
- Versioned
- Accompanied by a manifest
- Logged to the creative ledger
- Generated through governed tools whenever possible

This prevents creative work from becoming ad-hoc or lost.

## Core Tools

| Tool | Purpose |
|------|---------|
| `scripts/creative/creative_output.py` | Central CLI for the creative workflow |
| `scripts/creative/geography_of_ash_pipeline.py` | Generator for the Geography of Ash / American Shame Tapestry series |
| `scripts/creative/render_*.sh` | Standalone high-quality Bash renderers (full + lite) |
| `artifacts/creative/` | Storage for manifests and final artifacts |
| `data/creative_ledger.jsonl` | Append-only ledger of all creative actions |

## Basic Workflow

### 1. Register a New Creative Project

```bash
python scripts/creative/creative_output.py --action register --project my_new_piece
```

This creates a basic project structure under `scripts/creative/my_new_piece/`.

### 2. Generate Output

```bash
# High quality final version
python scripts/creative/creative_output.py --project geography_of_ash --action generate --mode full --assets ./my_assets/

# Fast preview version
python scripts/creative/creative_output.py --project geography_of_ash --action generate --mode lite --assets ./my_assets/
```

### 3. Create Manifest + Ledger Entry

```bash
python scripts/creative/creative_output.py --project geography_of_ash --action manifest --asset-name american_shame_tapestry_full.mp4
```

This generates a structured manifest and appends an entry to the creative ledger.

### 4. (Optional) Use Standalone Scripts

For maximum control or one-off renders, you can run the Bash scripts directly:

```bash
./scripts/creative/render_american_shame_tapestry.sh
./scripts/creative/render_american_shame_tapestry_lite.sh
```

## Project: Geography of Ash

This is currently the most developed creative project.

**Modes supported (via geography_of_ash_pipeline.py or creative_output.py):**
- `testimony` — Original high-quality single-scene render
- `full` — Complete multi-scene American Shame Tapestry
- `lite` — Fast preview version (1280x720, fast preset)
- `advanced` — **Maximum aggression** (emits complete hyper-stylized Bash renderer via `--mode advanced`)
- `manifest` — Generate ledger entry only

**Advanced / Hyper Effects (pushed May 2026):**
- Extreme per-era chromatic aberration via `geq` RGB channel sin/cos offsets
- Violent multi-split glitch transitions: RGB block scramble, frame stutter, datamosh-style addition/difference bursts at 0.017–0.041s periods
- Multi-layer kinetic text (primary high-amplitude + independent fast-jitter ghost/tear layers in accent colors with low alpha)
- Maximum per-era film destruction grain + eq crushing
- Dedicated Beast cyber-cow overlay during climax

The `--mode advanced` flag on the Python generator now outputs a fully self-contained, ready-to-execute hyper-aggressive render script (`render_american_shame_tapestry_hyper.sh` by default).

## Registered Creative Projects (Small Examples)

- **the_unburied** — Polished "small example". Extreme redacted-glitch + burial renderer, full docs, advanced pipeline + manifest support.
- **resistance_index** — Newest fully realized piece (registered live via the `register` command, then immediately built out). Hyper-stylized "ledger / index corruption" motif with fresh vertical-roll + typewriter-list destruction techniques, complete `docs/advanced_effects.md`, advanced pipeline, and rich manifest. Proves the workflow supports rapid, stylistically distinct expansion.
- **sovereign_dirt** — Earlier minimal registration example (still basic scaffold).

All projects follow the same governed contract: register first, manifest + ledger on every significant output, advanced effects expressed through reproducible Bash/Python generators.

## Best Practices

1. Always generate a manifest when releasing a new version of a creative artifact.
2. Log significant creative decisions to the ledger.
3. Prefer generating outputs through `creative_output.py` rather than raw one-off commands (for reproducibility).
4. Store final high-quality renders in `artifacts/creative/<project>/`.
5. Keep source assets organized but do not commit large binary video files to git unless necessary.

## Future Expansion

- Add support for new creative projects (audio pieces, generative visuals, installations).
- Integrate with DORK for AI-assisted creative generation under governance constraints.
- Add automated quality checks or "governance preflight" for creative outputs.
- Support for multi-format exports (vertical cuts, stills, audio stems).

---

*This workflow exists to ensure that even the most emotional or artistic expressions produced inside ADAAD remain traceable, reproducible, and constitutionally aligned.*