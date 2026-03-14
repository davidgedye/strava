#!/usr/bin/env python3
"""
fetch_missing_photos.py — Download photos for existing activities that don't
have a local photo yet, using the Strava API.

Reads ACCESS_TOKEN from environment.
Usage:
  ACCESS_TOKEN=... python3 fetch_missing_photos.py [data/history] [data/photos]
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

API_BASE = 'https://www.strava.com/api/v3'


def api_get(path, token):
    url = f'{API_BASE}{path}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    history_dir = Path(sys.argv[1] if len(sys.argv) > 1 else 'data/history')
    photos_dir  = Path(sys.argv[2] if len(sys.argv) > 2 else 'data/photos')

    token = os.environ.get('ACCESS_TOKEN')
    if not token:
        print('Error: ACCESS_TOKEN environment variable not set', file=sys.stderr)
        sys.exit(1)

    photos_dir.mkdir(parents=True, exist_ok=True)

    # Find all activity IDs that don't have a photo yet
    activity_files = list(history_dir.rglob('*.json'))
    activity_files = [f for f in activity_files if f.name != 'index.json'
                      and not f.name.startswith('activity-')
                      and not f.name.startswith('summary')]

    missing = []
    for f in activity_files:
        act_id = f.stem
        if not (photos_dir / f'{act_id}.jpg').exists():
            missing.append(act_id)

    print(f'Activities without photos: {len(missing)} of {len(activity_files)}')

    fetched = skipped = errors = 0
    for i, act_id in enumerate(missing, 1):
        try:
            photos = api_get(f'/activities/{act_id}/photos?size=2048', token)
            if not photos:
                skipped += 1
                continue
            url = photos[0].get('urls', {}).get('2048')
            if not url:
                skipped += 1
                continue
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                (photos_dir / f'{act_id}.jpg').write_bytes(resp.read())
            fetched += 1
            if fetched % 10 == 0:
                print(f'  [{i}/{len(missing)}] fetched={fetched} skipped={skipped} errors={errors}')
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'  WARN {act_id}: {e}')

        time.sleep(0.5)  # stay within Strava rate limits

    print(f'\nDone. fetched={fetched} no_photo={skipped} errors={errors}')


if __name__ == '__main__':
    main()
