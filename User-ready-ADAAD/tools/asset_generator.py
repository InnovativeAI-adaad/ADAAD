#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
ADAAD / Aponi - Agent Icon Pack v2.1
Asset normalizer + validator.

- Reads manifest.json
- Validates PNG palette adherence + contrast
- Normalizes PNG output (RGBA, sRGB-ish, size)
- Copies SVGs through (optional lint placeholder)
- Emits reports/metrics.jsonl entries
- Produces agent_pack_v2.1.zip

Designed for Pydroid3/Termux. Requires: pillow
  pip install pillow
"""

import json
import math
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Missing dependency: pillow. Install with: pip install pillow") from exc

ROOT = Path(__file__).resolve().parent  # .../User-ready-ADAAD/tools
PACK_DIR = ROOT.parent / "brand" / "v2" / "agent_pack_v2.1"
SRC_DIR = PACK_DIR / "src"
DIST_DIR = PACK_DIR / "dist"
REPORTS_DIR = ROOT.parent / "reports"
METRICS_PATH = REPORTS_DIR / "metrics.jsonl"
MANIFEST_PATH = PACK_DIR / "manifest.json"
ZIP_PATH = PACK_DIR / "agent_pack_v2.1.zip"

# Canon palette (RGB)
CYAN = (0x00, 0xE5, 0xFF)  # #00E5FF
VIOLET = (0x7B, 0x3F, 0xE4)  # #7B3FE4
PINK = (0xFF, 0x5F, 0xD2)  # #FF5FD2
MICRO = (0xCF, 0xE8, 0xFF)  # #CFE8FF


@dataclass
class CheckResult:
    ok: bool
    reason: str
    details: Dict


def ensure_dirs() -> None:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def srgb_to_linear(component: float) -> float:
    if component <= 0.04045:
        return component / 12.92
    return ((component + 0.055) / 1.055) ** 2.4


def rel_luminance(rgb: Tuple[int, int, int]) -> float:
    r, g, b = (value / 255.0 for value in rgb)
    r, g, b = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color_a: Tuple[int, int, int], color_b: Tuple[int, int, int]) -> float:
    luminance_a = rel_luminance(color_a)
    luminance_b = rel_luminance(color_b)
    l1, l2 = (luminance_a, luminance_b) if luminance_a >= luminance_b else (luminance_b, luminance_a)
    return (l1 + 0.05) / (l2 + 0.05)


def rgb_dist(color_a: Tuple[int, int, int], color_b: Tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(color_a, color_b)))


def sample_pixels(img: Image.Image, max_samples: int = 5000) -> List[Tuple[int, int, int, int]]:
    """
    Return up to `max_samples` RGBA tuples sampled uniformly.
    """
    rgba = img.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    if width * height <= max_samples:
        return [pixels[x, y] for y in range(height) for x in range(width)]
    step = int(math.sqrt((width * height) / max_samples)) + 1
    samples: List[Tuple[int, int, int, int]] = []
    for y in range(0, height, step):
        for x in range(0, width, step):
            samples.append(pixels[x, y])
            if len(samples) >= max_samples:
                return samples
    return samples


def contains_near_color(
    samples: List[Tuple[int, int, int, int]],
    target: Tuple[int, int, int],
    tolerance: float,
    alpha_min: int = 10,
) -> bool:
    for r, g, b, a in samples:
        if a < alpha_min:
            continue
        if rgb_dist((r, g, b), target) <= tolerance:
            return True
    return False


def dominant_color_distance(
    samples: List[Tuple[int, int, int, int]],
    target: Tuple[int, int, int],
    alpha_min: int = 10,
) -> float:
    """
    Approximate the average distance of non-transparent pixels to a target color.
    """
    total = 0.0
    count = 0
    for r, g, b, a in samples:
        if a < alpha_min:
            continue
        total += rgb_dist((r, g, b), target)
        count += 1
    if count == 0:
        return float("inf")
    return total / count


def estimate_foreground_rgb(
    samples: List[Tuple[int, int, int, int]],
    alpha_min: int = 10,
) -> Optional[Tuple[int, int, int]]:
    """
    Estimate the average foreground color from non-transparent pixels.
    """
    r_sum = g_sum = b_sum = count = 0
    for r, g, b, a in samples:
        if a < alpha_min:
            continue
        r_sum += r
        g_sum += g
        b_sum += b
        count += 1
    if count == 0:
        return None
    return (r_sum // count, g_sum // count, b_sum // count)


def write_metric(entry: Dict) -> None:
    with METRICS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_manifest() -> Dict:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_png(src_path: Path, out_path: Path, size: int) -> None:
    image = Image.open(src_path).convert("RGBA")
    if image.size != (size, size):
        image = image.resize((size, size), Image.LANCZOS)
    image.save(out_path, format="PNG", optimize=True)


def check_asset_png(asset_name: str, tier: str, variant: str, png_path: Path) -> List[CheckResult]:
    image = Image.open(png_path).convert("RGBA")
    samples = sample_pixels(image)

    rules: List[Tuple[str, bool]] = []
    if asset_name == "agent-active":
        rules.append(("has_cyan", contains_near_color(samples, CYAN, tolerance=40)))
        rules.append(("has_violet", contains_near_color(samples, VIOLET, tolerance=40)))
    elif asset_name == "agent-idle":
        rules.append(("has_violet", contains_near_color(samples, VIOLET, tolerance=45)))
    elif asset_name == "agent-error":
        rules.append(("has_pink", contains_near_color(samples, PINK, tolerance=45)))
    elif asset_name == "agent-micro":
        distance = dominant_color_distance(samples, MICRO)
        rules.append(("micro_avg_dist_ok", distance <= 35))
    else:
        return [CheckResult(ok=True, reason="no_rules", details={})]

    foreground = estimate_foreground_rgb(samples)
    contrast_ok = True
    contrast_details: Dict = {}
    if foreground is None:
        contrast_ok = False
        contrast_details = {"error": "no_foreground_pixels"}
    else:
        ratio_dark = contrast_ratio(foreground, (0, 0, 0))
        ratio_light = contrast_ratio(foreground, (255, 255, 255))
        contrast_ok = (ratio_dark >= 3.0) or (ratio_light >= 3.0)
        contrast_details = {"fg": foreground, "cr_dark": ratio_dark, "cr_light": ratio_light}

    results = [CheckResult(ok=bool(ok), reason=reason, details={}) for reason, ok in rules]
    results.append(CheckResult(ok=contrast_ok, reason="contrast_proxy", details=contrast_details))
    return results


def build_zip(zip_path: Path, base_dir: Path, include_paths: List[Path]) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in include_paths:
            absolute = base_dir / rel
            if absolute.is_dir():
                for path in absolute.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(base_dir))
            elif absolute.is_file():
                archive.write(absolute, rel)


def main() -> None:
    ensure_dirs()

    if not MANIFEST_PATH.is_file():
        raise SystemExit(f"Missing manifest: {MANIFEST_PATH}")

    manifest = load_manifest()
    assets = manifest.get("assets", [])
    if not assets:
        raise SystemExit("Manifest has no assets.")

    run_id = f"agent_pack_v2.1::{now_iso()}"
    write_metric({"ts": now_iso(), "type": "asset_pipeline_start", "run_id": run_id, "pack": "agent_pack_v2.1"})

    dist_written: List[str] = []

    for asset in assets:
        name = asset["name"]
        tier = asset.get("tier", "")
        variants = asset.get("variants", [])
        for variant in variants:
            if isinstance(variant, str) and variant.upper() == "SVG":
                src_svg = SRC_DIR / f"{name}.svg"
                out_svg = DIST_DIR / f"{name}.svg"
                if src_svg.is_file():
                    out_svg.write_bytes(src_svg.read_bytes())
                    dist_written.append(str(out_svg.relative_to(PACK_DIR)))
                    write_metric(
                        {
                            "ts": now_iso(),
                            "type": "asset_copy_svg",
                            "run_id": run_id,
                            "asset": name,
                            "tier": tier,
                            "ok": True,
                            "src": str(src_svg),
                            "dist": str(out_svg),
                        }
                    )
                else:
                    write_metric(
                        {
                            "ts": now_iso(),
                            "type": "asset_copy_svg",
                            "run_id": run_id,
                            "asset": name,
                            "tier": tier,
                            "ok": False,
                            "error": "missing_svg",
                            "path": str(src_svg),
                        }
                    )
                continue

            if isinstance(variant, str) and "x" in variant:
                size = int(variant.split("x")[0])
                src_png = SRC_DIR / f"{name}_{size}.png"
                out_png = DIST_DIR / f"{name}_{size}.png"
                if not src_png.is_file():
                    write_metric(
                        {
                            "ts": now_iso(),
                            "type": "asset_png_missing",
                            "run_id": run_id,
                            "asset": name,
                            "tier": tier,
                            "variant": variant,
                            "ok": False,
                            "path": str(src_png),
                        }
                    )
                    continue

                normalize_png(src_png, out_png, size=size)
                dist_written.append(str(out_png.relative_to(PACK_DIR)))

                checks = check_asset_png(name, tier, variant, out_png)
                all_ok = all(check.ok for check in checks)
                write_metric(
                    {
                        "ts": now_iso(),
                        "type": "asset_png_check",
                        "run_id": run_id,
                        "asset": name,
                        "tier": tier,
                        "variant": variant,
                        "ok": all_ok,
                        "checks": [{"ok": c.ok, "reason": c.reason, "details": c.details} for c in checks],
                        "src": str(src_png.relative_to(ROOT)),
                        "dist": str(out_png.relative_to(ROOT)),
                    }
                )

    include_paths = [MANIFEST_PATH.relative_to(PACK_DIR), Path("dist")]
    build_zip(ZIP_PATH, PACK_DIR, include_paths)

    write_metric(
        {
            "ts": now_iso(),
            "type": "asset_pipeline_done",
            "run_id": run_id,
            "pack": "agent_pack_v2.1",
            "zip": str(ZIP_PATH.relative_to(ROOT)),
            "dist_count": len(dist_written),
        }
    )

    print("OK")
    print(f"Dist: {DIST_DIR}")
    print(f"Zip: {ZIP_PATH}")
    print(f"Metrics: {METRICS_PATH}")


if __name__ == "__main__":
    main()
