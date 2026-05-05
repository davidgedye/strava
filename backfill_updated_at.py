#!/usr/bin/env python3
"""
One-time backfill: fetch updated_at from Strava for the last 7 days and
patch it into the activity-index.json stored in R2.

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
import urllib.request
from datetime import datetime

API_BASE = 'https://www.strava.com/api/v3'
R2_BUCKET = 's3://strava-data'
INDEX_KEY  = 'data/history/activity-index.json'


def api_get(path, token):
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

    # Patch updated_at into matching index entries
    patched = 0
    for a in recent:
        aid = str(a['id'])
        updated_at = a.get('updated_at', '')
        if aid in index and updated_at:
            entry = index[aid]
            if not isinstance(entry, dict):
                continue
            if entry.get('updated_at') != updated_at:
                entry['updated_at'] = updated_at
                patched += 1

    print(f'  {patched} entries patched with updated_at')

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

    print(f'Uploaded updated index. Done.')


if __name__ == '__main__':
    main()
