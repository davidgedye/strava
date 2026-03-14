#!/usr/bin/env python3
"""
extract_photos.py — One-time extraction of activity photos from a Strava export ZIP
to data/photos/{activity_id}.jpg

Usage:
  python3 extract_photos.py [path/to/stravaExport.zip] [data/photos]
"""

import csv
import io
import sys
import zipfile
from pathlib import Path


def main():
    zip_path = Path(sys.argv[1] if len(sys.argv) > 1 else 'stravaExport_3_7_2026.zip')
    out_dir  = Path(sys.argv[2] if len(sys.argv) > 2 else 'data/photos')

    if not zip_path.exists():
        print(f'ERROR: ZIP not found: {zip_path}', file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    extracted = skipped = missing = 0

    with zipfile.ZipFile(zip_path, 'r') as zf:
        zip_names = set(zf.namelist())

        candidates = [n for n in zip_names if n.endswith('activities.csv')]
        if not candidates:
            print('ERROR: activities.csv not found in ZIP', file=sys.stderr)
            sys.exit(1)

        with zf.open(candidates[0]) as f:
            rows = list(csv.DictReader(io.TextIOWrapper(f, encoding='utf-8')))

        total = sum(1 for r in rows if r.get('Activity ID') and r.get('Media'))
        print(f'Found {total} activities with media entries in {zip_path.name}')

        for row in rows:
            act_id = row.get('Activity ID', '').strip()
            media  = row.get('Media', '').strip()
            if not act_id or not media:
                continue

            out_path = out_dir / f'{act_id}.jpg'
            if out_path.exists():
                skipped += 1
                continue

            parts = [p.strip() for p in media.split('|') if p.strip()]
            jpgs  = [p for p in parts if p.lower().endswith('.jpg') and p in zip_names]

            if not jpgs:
                missing += 1
                continue

            out_path.write_bytes(zf.read(jpgs[0]))
            extracted += 1

            if (extracted + skipped) % 100 == 0:
                print(f'  [{extracted + skipped}/{total}] extracted={extracted} skipped={skipped} missing={missing}')

    print(f'\nDone. extracted={extracted} skipped(already exist)={skipped} missing(not in ZIP)={missing}')
    print(f'Photos saved to {out_dir}/')


if __name__ == '__main__':
    main()
