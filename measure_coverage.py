"""
Measure packing coverage of all existing strava layout files.

Coverage = sum(box_w * box_h) / tight_bounding_box_area
where box dimensions include CSS_MARGIN (stroke + padding) baked in,
and the denominator is the actual placed extent (not the full canvas).

Run before and after migrating to boxcraft to identify any regressions.
Results are saved to coverage_baseline.json for later comparison.
"""

from __future__ import annotations

import json
from pathlib import Path

LAYOUTS_DIR = Path(__file__).parent / "data" / "layouts"
OUTPUT      = Path(__file__).parent / "coverage_baseline.json"

CSS_MARGIN = 5   # STROKE_CSS*2 + PADDING_CSS — matches compute_layout.py


def measure_layout(path: Path) -> float | None:
    """
    Return coverage fraction for one layout file, or None if no spatial data.
    Coverage = sum(box areas) / tight bounding box area of all placed items.
    """
    layout = json.loads(path.read_text())
    acts = layout.get("activities", [])
    if not acts:
        return None

    scale       = layout["scale"]
    default_cos = layout.get("cos_lat", 1.0)

    boxes = []
    for act in acts:
        cos_lat = act.get("cos_lat", default_cos)

        if "coords" in act:
            coords = act["coords"]
            if not coords:
                continue
            lngs = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            w = (max(lngs) - min(lngs)) * cos_lat * scale + CSS_MARGIN
            h = (max(lats) - min(lats))             * scale + CSS_MARGIN
        elif "circle_radius" in act:
            d = 2 * act["circle_radius"] * scale + CSS_MARGIN
            w = h = d
        else:
            continue

        boxes.append((act["dx"], act["dy"], w, h))

    if not boxes:
        return None

    left   = min(cx - w / 2 for cx, cy, w, h in boxes)
    right  = max(cx + w / 2 for cx, cy, w, h in boxes)
    top    = min(cy - h / 2 for cx, cy, w, h in boxes)
    bottom = max(cy + h / 2 for cx, cy, w, h in boxes)
    bb_area = (right - left) * (bottom - top)
    if bb_area <= 0:
        return None

    return sum(w * h for _, _, w, h in boxes) / bb_area


# ── Run across all layout files ─────────────────────────────────────────────

results: dict[str, float] = {}

for path in sorted(LAYOUTS_DIR.glob("*.json")):
    if path.name == "index.json":
        continue
    cov = measure_layout(path)
    if cov is not None:
        results[path.stem] = round(cov, 6)

OUTPUT.write_text(json.dumps(results, indent=2))
print(f"Measured {len(results)} layouts → {OUTPUT}")
print()

coverages = list(results.values())
portrait  = [c for k, c in results.items() if not k.endswith("-land")]
landscape = [c for k, c in results.items() if k.endswith("-land")]

def stats(vals: list[float], label: str) -> None:
    print(f"{label} (n={len(vals)})")
    print(f"  mean={sum(vals)/len(vals):.1%}  "
          f"median={sorted(vals)[len(vals)//2]:.1%}  "
          f"min={min(vals):.1%}  max={max(vals):.1%}")

stats(coverages, "All")
stats(portrait,  "Portrait")
stats(landscape, "Landscape")
