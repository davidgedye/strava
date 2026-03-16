#!/usr/bin/env bash
# Render DZI super-images for all periods (years + months), both portrait and landscape.
# Social is excluded — run separately with a lower --scale if needed.
# Usage: bash render_dzi_all.sh [data/photos]
set -euo pipefail

PHOTOS_DIR="${1:-data/photos}"
LAYOUTS_DIR="data/layouts"

# Discover all non-social, non-hikes, non-week portrait layout files
mapfile -t PERIODS < <(
  ls "$LAYOUTS_DIR"/*.json \
  | xargs -I{} basename {} .json \
  | grep -v '\-land$' \
  | grep -v '^social$' \
  | grep -v '^hikes$' \
  | grep -v '^week$' \
  | grep -v '^index$' \
  | sort
)

TOTAL=${#PERIODS[@]}
echo "Found $TOTAL periods to render."

i=0
for period in "${PERIODS[@]}"; do
  i=$((i + 1))

  echo ""
  echo "══════════════════════════════════════════"
  echo "  [$i/$TOTAL] Period: $period (portrait)"
  echo "══════════════════════════════════════════"
  python3 render_dzi.py --period "$period" --photos-dir "$PHOTOS_DIR"
  echo "  ✓ $period portrait done"

  echo ""
  echo "──────────────────────────────────────────"
  echo "  [$i/$TOTAL] Period: $period (landscape)"
  echo "──────────────────────────────────────────"
  python3 render_dzi.py --period "$period" --photos-dir "$PHOTOS_DIR" --landscape
  echo "  ✓ $period landscape done"
done

echo ""
echo "══════════════════════════════════════════"
echo "  Hikes (portrait + landscape)"
echo "══════════════════════════════════════════"
python3 render_dzi.py --period hikes --photos-dir "$PHOTOS_DIR" --scale 20
echo "  ✓ hikes portrait done"
python3 render_dzi.py --period hikes --photos-dir "$PHOTOS_DIR" --scale 15 --landscape
echo "  ✓ hikes landscape done"

echo ""
echo "All done. DZI files written to data/dzi/"
