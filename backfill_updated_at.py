#!/usr/bin/env python3
"""
One-time backfill: patch updated_at into activity-index.json for the last 7 days
so that update-if-changed.yml can immediately start detecting modified activities.

updated_at is only available on the detail endpoint (GET /activities/{id}),
not the list endpoint, so we fetch each activity individually.

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

    # Fetch last 7 days from list endpoint to get candidate IDs
    seven_days_ago = int(time.time()) - 7 * 24 * 3600
    print('Fetching last 7 days of activities from Strava...')
    recent = api_get(f'/athlete/activities?after={seven_days_ago}&per_page=200', token)
    print(f'  {len(recent)} activities returned')

    # For each known activity, fetch detail to get updated_at
    patched = 0
    for a in recent:
        aid = str(a['id'])
        if aid not in index:
            continue
        entry = index[aid]
        if not isinstance(entry, dict):
            continue
        try:
            detail = api_get(f'/activities/{aid}', token)
            updated_at = detail.get('updated_at', '')
            if updated_at and entry.get('updated_at') != updated_at:
                entry['updated_at'] = updated_at
                patched += 1
                print(f'  Patched {aid}: {updated_at}')
            time.sleep(0.5)
        except Exception as e:
            print(f'  Warning: could not fetch detail for {aid}: {e}')

    print(f'{patched} entries patched with updated_at')

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
