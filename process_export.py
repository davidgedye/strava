#!/usr/bin/env python3
"""
Process a Strava export zip into nested JSON data files for the dashboard.

Usage:
    python3 process_export.py <export.zip> [output-dir]

Output structure:
    data/summary.json               — year-level totals (loaded once on app start)
    data/{year}/index.json          — month-level totals for that year
    data/{year}/{mm}/index.json     — week groupings + activity list (no tracks)
    data/{year}/{mm}/{id}.json      — individual activity with GeoJSON track
    data/activity-index.json        — flat {id: {year, month}} for incremental updates
"""

import sys
import csv
import gzip
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

import fitparse

METERS_PER_MILE = 1609.344
MAX_TRACK_POINTS = 500  # Decimate GPS tracks to at most this many points

# Activity types that count as "runs" for run-specific stats
RUN_TYPES = {'Run', 'Virtual Run', 'Trail Run'}


# --- GPS parsing ---

def semicircles_to_degrees(v):
    return v * (180.0 / 2**31)


def simplify(coords, max_points=MAX_TRACK_POINTS):
    """Uniformly decimate a coordinate list to at most max_points."""
    if len(coords) <= max_points:
        return coords
    step = len(coords) / max_points
    return [coords[int(i * step)] for i in range(max_points)]


def parse_fit(data):
    """Parse raw FIT bytes, return [[lng, lat, ele], ...] or None."""
    try:
        fitfile = fitparse.FitFile(io.BytesIO(data))
        coords = []
        for record in fitfile.get_messages('record'):
            fields = {f.name: f.value for f in record}
            lat = fields.get('position_lat')
            lng = fields.get('position_long')
            if lat is None or lng is None:
                continue
            ele = fields.get('enhanced_altitude') or fields.get('altitude')
            coords.append([
                round(semicircles_to_degrees(lng), 6),
                round(semicircles_to_degrees(lat), 6),
                round(float(ele), 1) if ele is not None else None,
            ])
        return coords or None
    except Exception:
        return None


def parse_gpx(data):
    """Parse raw GPX bytes, return [[lng, lat, ele], ...] or None."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(data)
        ns = {'g': 'http://www.topografix.com/GPX/1/1'}
        coords = []
        for pt in root.findall('.//g:trkpt', ns):
            lat = float(pt.get('lat'))
            lng = float(pt.get('lon'))
            ele_el = pt.find('g:ele', ns)
            ele = round(float(ele_el.text), 1) if ele_el is not None else None
            coords.append([round(lng, 6), round(lat, 6), ele])
        return coords or None
    except Exception:
        return None


def get_track(zf, filename):
    """Read and parse a GPS file from the zip. Returns simplified coords or None."""
    if not filename:
        return None
    try:
        data = zf.read(filename)
    except KeyError:
        return None

    if filename.endswith('.fit.gz'):
        with gzip.open(io.BytesIO(data)) as gz:
            coords = parse_fit(gz.read())
    elif filename.endswith('.fit'):
        coords = parse_fit(data)
    elif filename.endswith('.gpx.gz'):
        with gzip.open(io.BytesIO(data)) as gz:
            coords = parse_gpx(gz.read())
    elif filename.endswith('.gpx'):
        coords = parse_gpx(data)
    else:
        return None

    return simplify(coords) if coords else None


# --- CSV parsing ---

def parse_date(s):
    """Parse Strava's export date format: 'Apr 6, 2014, 3:31:03 PM'"""
    return datetime.strptime(s.strip(), '%b %d, %Y, %I:%M:%S %p')


def float_or_none(s):
    s = s.strip()
    return float(s) if s else None


def flag(s):
    """Convert '1.0'/'0.0' flag to bool, or None if absent."""
    s = s.strip()
    return float(s) == 1.0 if s else None


def parse_row(row):
    """Extract fields from a CSV row by column index. Returns dict or None."""
    if len(row) < 35:
        return None
    try:
        dt = parse_date(row[1])
    except ValueError:
        return None

    distance_m = float_or_none(row[17]) or 0.0
    moving_time = float_or_none(row[16])
    elevation_m = float_or_none(row[20])
    avg_hr = float_or_none(row[31])
    max_hr = float_or_none(row[7])
    avg_cadence = float_or_none(row[29])
    calories = float_or_none(row[34])
    description = row[4].strip() or None
    with_pet = flag(row[94]) if len(row) > 94 else None
    with_kid = flag(row[98]) if len(row) > 98 else None

    return {
        'id': row[0].strip(),
        'name': row[2].strip(),
        'type': row[3].strip(),
        'date': dt.strftime('%Y-%m-%dT%H:%M:%S'),
        'description': description,
        'filename': row[12].strip(),
        'year': dt.year,
        'month': dt.month,
        'week': f'{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}',
        'distance_mi': round(distance_m / METERS_PER_MILE, 2),
        'moving_time_s': int(moving_time) if moving_time else None,
        'elevation_m': round(elevation_m, 1) if elevation_m else None,
        'avg_hr': round(avg_hr) if avg_hr else None,
        'max_hr': round(max_hr) if max_hr else None,
        'avg_cadence': round(avg_cadence) if avg_cadence else None,
        'calories': round(calories) if calories else None,
        'with_pet': with_pet,
        'with_kid': with_kid,
    }


# --- Aggregation ---

def summarize(activities):
    """Compute totals over a list of activity dicts."""
    runs = [a for a in activities if a['type'] in RUN_TYPES]
    return {
        'count': len(activities),
        'run_count': len(runs),
        'distance_mi': round(sum(a['distance_mi'] for a in activities), 2),
        'run_distance_mi': round(sum(a['distance_mi'] for a in runs), 2),
        'elevation_m': round(sum(a['elevation_m'] or 0 for a in activities), 1),
    }


def activity_stub(a):
    """Activity metadata without filename — safe to embed in index files."""
    return {k: v for k, v in a.items() if k not in ('filename', 'year', 'month', 'week')}


# --- Main ---

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    zip_path = sys.argv[1]
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else 'data')

    print(f'Reading {zip_path} ...')

    # First pass: read all CSV rows
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open('activities.csv') as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding='utf-8'))
            next(reader)  # skip headers
            csv_rows = list(reader)

    print(f'Found {len(csv_rows)} activities in CSV')

    # Parse all rows
    activities = []
    for row in csv_rows:
        parsed = parse_row(row)
        if parsed:
            activities.append(parsed)
        else:
            print(f'  Skipping row: {row[:3]}')

    # Sort chronologically
    activities.sort(key=lambda a: a['date'])

    # Second pass: extract GPS tracks and write individual activity files
    print('Extracting GPS tracks and writing activity files ...')
    with zipfile.ZipFile(zip_path) as zf:
        for i, act in enumerate(activities):
            if (i + 1) % 200 == 0:
                print(f'  {i + 1}/{len(activities)} ...')

            track = get_track(zf, act['filename'])

            act_dir = out_dir / str(act['year']) / f"{act['month']:02d}"
            act_dir.mkdir(parents=True, exist_ok=True)

            act_data = activity_stub(act)
            act_data['has_track'] = track is not None
            if track:
                act_data['track'] = {'type': 'LineString', 'coordinates': track}

            with open(act_dir / f"{act['id']}.json", 'w') as f:
                json.dump(act_data, f, separators=(',', ':'))

    # Build nested summary structure
    print('Building summary files ...')

    # Group: year -> month -> week -> [activities]
    tree = {}
    for act in activities:
        y, m, w = act['year'], act['month'], act['week']
        tree.setdefault(y, {}).setdefault(m, {}).setdefault(w, []).append(act)

    year_summaries = []

    for year in sorted(tree):
        month_summaries = []

        for month in sorted(tree[year]):
            week_summaries = []

            for week in sorted(tree[year][month]):
                week_acts = tree[year][month][week]
                week_summary = {
                    'week': week,
                    **summarize(week_acts),
                    'activities': [activity_stub(a) for a in week_acts],
                }
                week_summaries.append(week_summary)

            month_acts = [a for w in tree[year][month].values() for a in w]
            month_summary = {
                'month': month,
                **summarize(month_acts),
                'weeks': week_summaries,
            }
            month_summaries.append(month_summary)

            month_dir = out_dir / str(year) / f'{month:02d}'
            month_dir.mkdir(parents=True, exist_ok=True)
            with open(month_dir / 'index.json', 'w') as f:
                json.dump(month_summary, f, separators=(',', ':'))

        year_acts = [a for m in tree[year].values() for w in m.values() for a in w]
        year_summary = {
            'year': year,
            **summarize(year_acts),
            'months': month_summaries,
        }
        year_summaries.append(year_summary)

        year_dir = out_dir / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)
        with open(year_dir / 'index.json', 'w') as f:
            json.dump(year_summary, f, separators=(',', ':'))

    # Top-level summary: years only (no month detail — keeps it tiny)
    summary = {
        'years': [{k: v for k, v in y.items() if k != 'months'} for y in year_summaries],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / 'summary.json', 'w') as f:
        json.dump(summary, f, separators=(',', ':'))

    # Activity index for incremental updates
    activity_index = {a['id']: {'year': a['year'], 'month': a['month']} for a in activities}
    with open(out_dir / 'activity-index.json', 'w') as f:
        json.dump(activity_index, f, separators=(',', ':'))

    print(f'\nDone. {len(activities)} activities written to {out_dir}/')
    print(f'  {sum(1 for a in activities if a["type"] in RUN_TYPES)} runs')
    print(f'  {sum(1 for a in activities if a["type"] not in RUN_TYPES)} other activities')


if __name__ == '__main__':
    main()
