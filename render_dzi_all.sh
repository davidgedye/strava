#!/usr/bin/env bash
# Render DZI super-images for all periods (years + months), both portrait and landscape.
# Social is excluded — run separately with a lower --scale if needed.
# Usage: bash render_dzi_all.sh [path/to/export.zip]
set -euo pipefail

ZIP="${1:-stravaExport_3_7_2026.zip}"
LAYOUTS_DIR="data/layouts"

# Discover all non-social, non-week portrait layout files
mapfile -t PERIODS < <(
  ls "$LAYOUTS_DIR"/*.json \
  | xargs -I{} basename {} .json \
  | grep -v '\-land$' \
  | grep -v '^social$' \
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
  python3 render_dzi.py --period "$period" --zip "$ZIP"
  echo "  ✓ $period portrait done"

  echo ""
  echo "──────────────────────────────────────────"
  echo "  [$i/$TOTAL] Period: $period (landscape)"
  echo "──────────────────────────────────────────"
  python3 render_dzi.py --period "$period" --zip "$ZIP" --landscape
  echo "  ✓ $period landscape done"
done

echo ""
echo "All done. DZI files written to data/dzi/"
