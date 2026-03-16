#!/usr/bin/env python3
"""
backfill_activities.py — Fetch all activities since a given date from the Strava
API and add any missing from data/history/, then download their photos.

Reads ACCESS_TOKEN from environment.
Usage:
  ACCESS_TOKEN=... python3 backfill_activities.py --since 2026-03-07
                                                  [--history data/history]
                                                  [--photos  data/photos]
                                                  [--force-ids ID1,ID2,...]

  --force-ids  Re-fetch specific activity IDs even if they already exist,
               overwriting the history JSON and re-downloading their photos.
               Can be combined with --since or used alone.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from incremental_update import (
    api_get, parse_activity, fetch_description, fetch_track, fetch_photo,
    activity_stub, rebuild_month_index, rebuild_year_index, rebuild_summary,
)
from social_classifier import is_with_friends

API_BASE = 'https://www.strava.com/api/v3'


def fetch_all_activities_since(since_ts, token):
    """Fetch all activities after since_ts (Unix timestamp) via paginated API."""
    activities = []
    page = 1
    while True:
        batch = api_get(
            f'/athlete/activities?after={since_ts}&per_page=100&page={page}',
            token,
        )
        if not batch:
            break
        activities.extend(batch)
        print(f'  Fetched page {page}: {len(batch)} activities ({len(activities)} total)')
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.5)
    return activities


def force_refetch_activity(act_id, token, history_dir, photos_dir):
    """Re-fetch a specific activity by ID, overwriting history JSON and photo."""
    print(f'Force-refetching activity {act_id} ...')
    raw = api_get(f'/activities/{act_id}', token)
    if not raw:
        print(f'  ERROR: could not fetch activity {act_id}', file=sys.stderr)
        return None

    act   = parse_activity(raw)
    desc  = fetch_description(act_id, token)
    track = fetch_track(act_id, token)
    time.sleep(0.5)

    act_dir = history_dir / str(act['year']) / f"{act['month']:02d}"
    act_dir.mkdir(parents=True, exist_ok=True)

    act_data = activity_stub(act)
    act_data['description']  = desc or None
    act_data['with_friends'] = is_with_friends(act['name'], desc)
    act_data['has_track']    = track is not None
    if track:
        act_data['track'] = {'type': 'LineString', 'coordinates': track}

    out_path = act_dir / f"{act['id']}.json"
    with open(out_path, 'w') as f:
        json.dump(act_data, f, separators=(',', ':'))
    print(f'  ✓ history updated: {out_path.relative_to(history_dir)}  ({act["type"]}, {act["distance_mi"]} mi)')

    # Re-download photo (delete existing first so fetch_photo will save fresh)
    photo_path = photos_dir / f'{act_id}.jpg'
    if photo_path.exists():
        photo_path.unlink()
    if raw.get('total_photo_count', 0) > 0:
        if fetch_photo(act_id, token, photos_dir):
            print(f'  ✓ photo re-downloaded for {act_id}')
        else:
            print(f'  ✗ no photo available for {act_id}')
    else:
        print(f'  – no photo on Strava for {act_id}')

    return act


def main():
    ap = argparse.ArgumentParser(description='Backfill missing activities and photos')
    ap.add_argument('--since',     default=None, help='Fetch activities on or after this date (YYYY-MM-DD)')
    ap.add_argument('--history',   default='data/history', help='History directory')
    ap.add_argument('--photos',    default='data/photos',  help='Photos directory')
    ap.add_argument('--force-ids', default=None, help='Comma-separated activity IDs to re-fetch unconditionally')
    args = ap.parse_args()

    if not args.since and not args.force_ids:
        print('Error: at least one of --since or --force-ids is required', file=sys.stderr)
        sys.exit(1)

    token = os.environ.get('ACCESS_TOKEN')
    if not token:
        print('Error: ACCESS_TOKEN environment variable not set', file=sys.stderr)
        sys.exit(1)

    history_dir = Path(args.history)
    photos_dir  = Path(args.photos)
    photos_dir.mkdir(parents=True, exist_ok=True)

    # Load existing activity index
    index_file = history_dir / 'activity-index.json'
    activity_index = {}
    if index_file.exists():
        with open(index_file) as f:
            activity_index = json.load(f)
    print(f'Known activities: {len(activity_index)}')

    affected_months = set()

    # ── Force-refetch specific IDs ─────────────────────────────────────────────
    if args.force_ids:
        ids = [i.strip() for i in args.force_ids.split(',') if i.strip()]
        print(f'\nForce-refetching {len(ids)} specific activities ...')
        for act_id in ids:
            act = force_refetch_activity(act_id, token, history_dir, photos_dir)
            if act:
                activity_index[act['id']] = {'year': act['year'], 'month': act['month']}
                affected_months.add((act['year'], act['month']))
            time.sleep(0.5)

    # ── Backfill since a date ──────────────────────────────────────────────────
    if args.since:
        since_dt = datetime.strptime(args.since, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        since_ts = int(since_dt.timestamp())
        print(f'\nFetching all activities since {args.since} (ts={since_ts}) ...')

        all_activities = fetch_all_activities_since(since_ts, token)
        new_activities = [a for a in all_activities if str(a['id']) not in activity_index]
        print(f'Activities since {args.since}: {len(all_activities)}  |  New (missing from history): {len(new_activities)}')

        for a in new_activities:
            act   = parse_activity(a)
            desc  = fetch_description(a['id'], token)
            track = fetch_track(a['id'], token)
            time.sleep(0.5)

            act_dir = history_dir / str(act['year']) / f"{act['month']:02d}"
            act_dir.mkdir(parents=True, exist_ok=True)

            act_data = activity_stub(act)
            act_data['description']  = desc or None
            act_data['with_friends'] = is_with_friends(act['name'], desc)
            act_data['has_track']    = track is not None
            if track:
                act_data['track'] = {'type': 'LineString', 'coordinates': track}

            out_path = act_dir / f"{act['id']}.json"
            with open(out_path, 'w') as f:
                json.dump(act_data, f, separators=(',', ':'))

            social_tag = ' 👥' if act_data['with_friends'] else ''
            print(f'  + {out_path.relative_to(history_dir)}  ({act["type"]}, {act["distance_mi"]} mi){social_tag}')
            activity_index[act['id']] = {'year': act['year'], 'month': act['month']}
            affected_months.add((act['year'], act['month']))

        # Fetch photos for new activities and any without a photo yet
        photo_candidates = [a for a in all_activities if a.get('total_photo_count', 0) > 0]
        print(f'\nActivities with photos since {args.since}: {len(photo_candidates)}')
        fetched = skipped = errors = 0
        for a in photo_candidates:
            act_id = str(a['id'])
            out_path = photos_dir / f'{act_id}.jpg'
            if out_path.exists():
                skipped += 1
                continue
            if fetch_photo(act_id, token, photos_dir):
                fetched += 1
                print(f'  → photo saved for {act_id}')
            else:
                errors += 1
            time.sleep(0.5)
        print(f'photos_fetched={fetched} already_have_photo={skipped} errors={errors}')

    # ── Rebuild indices ────────────────────────────────────────────────────────
    if affected_months:
        affected_years = set()
        for year, month in sorted(affected_months):
            print(f'Rebuilding {year}/{month:02d}/index.json ...')
            rebuild_month_index(year, month, history_dir)
            affected_years.add(year)
        for year in sorted(affected_years):
            print(f'Rebuilding {year}/index.json ...')
            rebuild_year_index(year, history_dir)
        print('Rebuilding summary.json ...')
        rebuild_summary(history_dir)
        with open(index_file, 'w') as f:
            json.dump(activity_index, f, separators=(',', ':'))

    print('\nDone.')


if __name__ == '__main__':
    main()
