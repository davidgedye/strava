#!/usr/bin/env python3
"""
One-time backfill: patch photo_count into activity-index.json for the last 7 days
so that update-if-changed.yml can immediately start detecting photo additions.

Usage:
    ACCESS_TOKEN=<token> \
    AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> R2_ENDPOINT=<url> \
    python3 backfill_updated_at.py
"""

import json
import os
import subprocess
import sys
import time

API_BASE = 'https://www.strava.com/api/v3'
R2_BUCKET = 's3://strava-data'
INDEX_KEY  = 'data/history/activity-index.json'


def api_get(path, token):
    import urllib.request
    req = urllib.request.Request(
        f'{API_BASE}{path}',
        headers={'Authorization': f'Bearer {token}'},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def r2(args):
    endpoint = os.environ['R2_ENDPOINT']
    result = subprocess.run(
        ['aws', 's3'] + args + ['--endpoint-url', endpoint],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout


def main():
    token = os.environ.get('ACCESS_TOKEN')
    if not token:
        print('Error: ACCESS_TOKEN not set', file=sys.stderr)
        sys.exit(1)

    # Download current index from R2
    print('Downloading activity-index.json from R2...')
    raw = r2(['cp', f'{R2_BUCKET}/{INDEX_KEY}', '-'])
    index = json.loads(raw)
    print(f'  {len(index)} entries in index')

    # Fetch last 7 days from Strava
    seven_days_ago = int(time.time()) - 7 * 24 * 3600
    print('Fetching last 7 days of activities from Strava...')
    recent = api_get(f'/athlete/activities?after={seven_days_ago}&per_page=200', token)
    print(f'  {len(recent)} activities returned')
    if recent:
        a0 = recent[0]
        print(f'  Sample: id={a0["id"]} total_photo_count={a0.get("total_photo_count")} in_index={str(a0["id"]) in index}')

    # Patch photo_count into matching index entries
    patched = 0
    for a in recent:
        aid = str(a['id'])
        if aid not in index:
            continue
        entry = index[aid]
        if not isinstance(entry, dict):
            continue
        photo_count = a.get('total_photo_count', 0)
        if entry.get('photo_count') != photo_count:
            entry['photo_count'] = photo_count
            patched += 1

    print(f'  {patched} entries patched with photo_count')

    if patched == 0:
        print('Nothing to upload.')
        return

    # Upload updated index back to R2
    updated_json = json.dumps(index, separators=(',', ':'))
    upload = subprocess.run(
        ['aws', 's3', 'cp', '-', f'{R2_BUCKET}/{INDEX_KEY}',
         '--endpoint-url', os.environ['R2_ENDPOINT']],
        input=updated_json, capture_output=True, text=True,
    )
    if upload.returncode != 0:
        print(upload.stderr, file=sys.stderr)
        sys.exit(1)

    print('Uploaded updated index. Done.')


if __name__ == '__main__':
    main()
