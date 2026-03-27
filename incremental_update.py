#!/usr/bin/env python3
"""
Incrementally update data/history/ from the Strava API.

Reads ACCESS_TOKEN from the environment variable of the same name.
Fetches the 30 most recent activities, adds any whose IDs are not already
in data/history/activity-index.json, then rebuilds all affected index files.

Usage:
    ACCESS_TOKEN=<token> python3 incremental_update.py [data/history]
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from social_classifier import is_with_friends

METERS_PER_MILE = 1609.344
MAX_TRACK_POINTS = 500
API_BASE = 'https://www.strava.com/api/v3'

# Map Strava API sport_type values → the type strings used in our JSON
SPORT_TYPE_MAP = {
    'Run':        'Run',
    'TrailRun':   'Trail Run',
    'VirtualRun': 'Virtual Run',
    'Treadmill':  'Virtual Run',
}

RUN_TYPES = {'Run', 'Virtual Run', 'Trail Run'}


# ── API ───────────────────────────────────────────────────────────────────────

def api_get(path, token):
    url = f'{API_BASE}{path}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ── GPS ───────────────────────────────────────────────────────────────────────

def simplify(coords, max_points=MAX_TRACK_POINTS):
    if len(coords) <= max_points:
        return coords
    step = (len(coords) - 1) / (max_points - 1)
    indices = set(round(i * step) for i in range(max_points))
    indices.add(0)
    indices.add(len(coords) - 1)
    return [coords[i] for i in sorted(indices)]


def fetch_track(activity_id, token):
    """Fetch and simplify a GPS track. Returns [[lng, lat, ele], ...] or None."""
    try:
        data = api_get(
            f'/activities/{activity_id}/streams'
            f'?keys=latlng,altitude&key_by_type=true',
            token,
        )
        latlng    = data.get('latlng',    {}).get('data', [])
        altitudes = data.get('altitude',  {}).get('data', [])
        if not latlng:
            return None
        coords = []
        for i, (lat, lng) in enumerate(latlng):
            ele = altitudes[i] if i < len(altitudes) else None
            coords.append([
                round(lng, 6),
                round(lat, 6),
                round(float(ele), 1) if ele is not None else None,
            ])
        return simplify(coords) if coords else None
    except Exception as e:
        print(f'  Warning: could not fetch track for {activity_id}: {e}')
        return None


def fetch_description(activity_id, token):
    """Fetch the full activity detail to get its description."""
    try:
        data = api_get(f'/activities/{activity_id}', token)
        return data.get('description') or ''
    except Exception as e:
        print(f'  Warning: could not fetch description for {activity_id}: {e}')
        return ''


def fetch_photo(activity_id, token, photos_dir):
    """Download the primary photo for an activity to photos_dir/{activity_id}.jpg."""
    try:
        photos = api_get(f'/activities/{activity_id}/photos?size=2048', token)
        if not photos:
            return False
        url = photos[0].get('urls', {}).get('2048')
        if not url:
            return False
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            (photos_dir / f'{activity_id}.jpg').write_bytes(resp.read())
        return True
    except Exception as e:
        print(f'  Warning: could not fetch photo for {activity_id}: {e}')
        return False


# ── PARSING ───────────────────────────────────────────────────────────────────

def parse_activity(a):
    """Convert a Strava API activity dict to our internal format."""
    dt = datetime.fromisoformat(a['start_date_local'].replace('Z', ''))
    sport_type = a.get('sport_type') or a.get('type', '')
    act_type   = SPORT_TYPE_MAP.get(sport_type, sport_type)

    distance_m = a.get('distance') or 0.0
    moving_time = a.get('moving_time')
    elevation_m = a.get('total_elevation_gain')
    avg_hr      = a.get('average_heartrate')
    max_hr      = a.get('max_heartrate')
    avg_cadence = a.get('average_cadence')
    calories    = a.get('calories')

    return {
        'id':            str(a['id']),
        'name':          a.get('name', ''),
        'type':          act_type,
        'date':          dt.strftime('%Y-%m-%dT%H:%M:%S'),
        'description':   None,
        'year':          dt.year,
        'month':         dt.month,
        'week':          f'{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}',
        'distance_mi':   round(distance_m / METERS_PER_MILE, 2),
        'moving_time_s': int(moving_time) if moving_time else None,
        'elevation_m':   round(elevation_m, 1) if elevation_m else None,
        'avg_hr':        round(avg_hr) if avg_hr else None,
        'max_hr':        round(max_hr) if max_hr else None,
        'avg_cadence':   round(avg_cadence) if avg_cadence else None,
        'calories':      round(calories) if calories else None,
        'with_pet':      None,
        'with_kid':      None,
        'with_friends':  None,
    }


def activity_stub(a):
    """Drop internal-only fields before writing to index files."""
    return {k: v for k, v in a.items() if k not in ('year', 'month', 'week')}


# ── AGGREGATION ───────────────────────────────────────────────────────────────

def summarize(activities):
    runs = [a for a in activities if a.get('type') in RUN_TYPES]
    return {
        'count':           len(activities),
        'run_count':       len(runs),
        'distance_mi':     round(sum(a['distance_mi'] for a in activities), 2),
        'run_distance_mi': round(sum(a['distance_mi'] for a in runs), 2),
        'elevation_m':     round(sum(a.get('elevation_m') or 0 for a in activities), 1),
    }


# ── INDEX REBUILD ─────────────────────────────────────────────────────────────

def read_month_activities(month_dir):
    """Read all individual activity files in a month directory."""
    activities = []
    for p in month_dir.glob('*.json'):
        if p.name == 'index.json':
            continue
        with open(p) as f:
            act = json.load(f)
        dt = datetime.fromisoformat(act['date'])
        act['year']  = dt.year
        act['month'] = dt.month
        act['week']  = f'{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}'
        activities.append(act)
    return sorted(activities, key=lambda a: a['date'])


def rebuild_month_index(year, month, out_dir):
    month_dir  = out_dir / str(year) / f'{month:02d}'
    activities = read_month_activities(month_dir)

    weeks = {}
    for act in activities:
        weeks.setdefault(act['week'], []).append(act)

    week_summaries = [
        {'week': week, **summarize(acts), 'activities': [activity_stub(a) for a in acts]}
        for week, acts in sorted(weeks.items())
    ]

    month_summary = {'month': month, **summarize(activities), 'weeks': week_summaries}
    with open(month_dir / 'index.json', 'w') as f:
        json.dump(month_summary, f, separators=(',', ':'))
    return month_summary


def rebuild_year_index(year, out_dir):
    year_dir = out_dir / str(year)
    month_summaries = []
    for month_dir in sorted(year_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        index_file = month_dir / 'index.json'
        if index_file.exists():
            with open(index_file) as f:
                month_summaries.append(json.load(f))

    # Flatten to activity stubs for year-level summarize()
    all_acts = [
        act
        for ms in month_summaries
        for ws in ms.get('weeks', [])
        for act in ws.get('activities', [])
    ]
    year_summary = {'year': year, **summarize(all_acts), 'months': month_summaries}
    with open(year_dir / 'index.json', 'w') as f:
        json.dump(year_summary, f, separators=(',', ':'))
    return year_summary


def rebuild_summary(out_dir):
    year_summaries = []
    for year_dir in sorted(out_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        index_file = year_dir / 'index.json'
        if index_file.exists():
            with open(index_file) as f:
                year_summaries.append(json.load(f))

    summary = {'years': [{k: v for k, v in y.items() if k != 'months'} for y in year_summaries]}
    with open(out_dir / 'summary.json', 'w') as f:
        json.dump(summary, f, separators=(',', ':'))


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else 'data/history')

    token = os.environ.get('ACCESS_TOKEN')
    if not token:
        print('Error: ACCESS_TOKEN environment variable not set', file=sys.stderr)
        sys.exit(1)

    # Load existing activity index
    index_file = out_dir / 'activity-index.json'
    activity_index = {}
    if index_file.exists():
        with open(index_file) as f:
            activity_index = json.load(f)
    print(f'Known activities: {len(activity_index)}')

    # Fetch recent activities and find new ones
    print('Fetching recent activities from Strava API...')
    recent = api_get('/athlete/activities?per_page=5', token)
    new_activities = [a for a in recent if str(a['id']) not in activity_index]
    print(f'New activities to add: {len(new_activities)}')

    has_new = bool(new_activities)
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            f.write(f'new_activities={"true" if has_new else "false"}\n')

    if not has_new:
        print('Nothing to do.')
        return

    # Write individual activity files
    photos_dir = out_dir.parent / 'photos'
    photos_dir.mkdir(parents=True, exist_ok=True)

    affected_months = set()
    for a in new_activities:
        act   = parse_activity(a)
        desc  = fetch_description(a['id'], token)
        track = fetch_track(a['id'], token)

        act_dir = out_dir / str(act['year']) / f"{act['month']:02d}"
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

        if a.get('total_photo_count', 0) > 0:
            photo_out = photos_dir / f'{act["id"]}.jpg'
            if not photo_out.exists():
                if fetch_photo(act['id'], token, photos_dir):
                    print(f'  → photo downloaded')
            time.sleep(0.5)

        social_tag = ' 👥' if act_data['with_friends'] else ''
        print(f'  + {out_path.relative_to(out_dir)}  ({act["type"]}, {act["distance_mi"]} mi){social_tag}')
        activity_index[act['id']] = {'year': act['year'], 'month': act['month']}
        affected_months.add((act['year'], act['month']))

        time.sleep(0.5)   # stay well within Strava rate limits

    # Rebuild affected month → year → summary indices
    affected_years = set()
    for year, month in sorted(affected_months):
        print(f'Rebuilding {year}/{month:02d}/index.json ...')
        rebuild_month_index(year, month, out_dir)
        affected_years.add(year)

    for year in sorted(affected_years):
        print(f'Rebuilding {year}/index.json ...')
        rebuild_year_index(year, out_dir)

    print('Rebuilding summary.json ...')
    rebuild_summary(out_dir)

    with open(index_file, 'w') as f:
        json.dump(activity_index, f, separators=(',', ':'))

    print(f'\nDone. {len(new_activities)} new activit{"y" if len(new_activities) == 1 else "ies"} added.')


if __name__ == '__main__':
    main()
