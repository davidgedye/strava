#!/usr/bin/env python3
"""
affected_periods.py — Given a list of changed activity IDs and a change type,
determine which layout periods and DZI periods need to be recomputed.

Usage:
    python3 affected_periods.py \
        --ids 12345678,87654321 \
        --change-type photo|route|social|type \
        --history data/history \
        [--previous-types Run,Hike]   # parallel to --ids, required for change-type=type

Outputs a JSON manifest to stdout:
    {
        "layout_periods": ["2021-06", "2021"],
        "dzi_periods":    ["2021-06", "2021"],
        "needs_strava_json": false
    }
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

RUN_TYPES  = {'Run', 'Trail Run', 'Virtual Run', 'TrailRun', 'VirtualRun', 'Treadmill'}
HIKE_TYPES = {'Hike', 'Walk', 'Snowshoe'}


def parse_dt(s):
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def current_periods():
    now = datetime.now(tz=timezone.utc)
    dow = now.weekday()
    week_start = (now - timedelta(days=dow)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return {
        'week_start': week_start,
        'month':      f"{now.year}-{now.month:02d}",
        'year':       str(now.year),
        'now':        now + timedelta(hours=2),
    }


def find_activity(history_dir: Path, activity_id: str):
    """Search history directory tree for {activity_id}.json."""
    for year_dir in sorted(history_dir.iterdir()):
        if not year_dir.is_dir():
            continue
        try:
            int(year_dir.name)
        except ValueError:
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            f = month_dir / f'{activity_id}.json'
            if f.exists():
                return json.loads(f.read_text())
    return None


def activity_type(act):
    return act.get('sport_type') or act.get('type') or ''


def periods_for_activity(act, cur, type_override=None):
    """Return set of period keys that contain this activity."""
    atype = type_override or activity_type(act)
    dt    = parse_dt(act['date'])
    mk    = f"{dt.year}-{dt.month:02d}"
    yk    = str(dt.year)

    periods = set()

    if atype in RUN_TYPES:
        periods.add(mk)
        periods.add(yk)
        if cur['week_start'] <= dt < cur['now']:
            periods.add('week')
        if act.get('with_friends'):
            periods.add('social')

    elif atype in HIKE_TYPES:
        periods.add('hikes')

    return periods


def main():
    # Parse args manually to stay consistent with other scripts in the project
    def get_arg(name):
        for i, a in enumerate(sys.argv):
            if a == name and i + 1 < len(sys.argv):
                return sys.argv[i + 1]
            if a.startswith(name + '='):
                return a.split('=', 1)[1]
        return None

    ids_raw            = get_arg('--ids')
    history_path       = get_arg('--history') or 'data/history'
    previous_types_raw = get_arg('--previous-types')

    if not ids_raw:
        print('ERROR: --ids is required', file=sys.stderr)
        sys.exit(1)

    activity_ids   = [i.strip() for i in ids_raw.split(',') if i.strip()]
    previous_types = ([t.strip() for t in previous_types_raw.split(',')]
                      if previous_types_raw else [])

    if previous_types and len(previous_types) != len(activity_ids):
        print('ERROR: --previous-types must have the same number of entries as --ids',
              file=sys.stderr)
        sys.exit(1)

    history_dir = Path(history_path)
    cur = current_periods()

    periods   = set()
    found_any = False

    for idx, act_id in enumerate(activity_ids):
        act = find_activity(history_dir, act_id)
        if act is None:
            print(f'WARN: activity {act_id} not found in {history_path}', file=sys.stderr)
            continue
        found_any = True

        # Current periods this activity belongs to
        periods |= periods_for_activity(act, cur)

        # If the activity type changed, also recompute the old-type periods
        if idx < len(previous_types):
            periods |= periods_for_activity(act, cur, type_override=previous_types[idx])

    if not found_any:
        print('ERROR: none of the specified activity IDs were found in history', file=sys.stderr)
        sys.exit(1)

    manifest = {
        'layout_periods': sorted(periods),
        'dzi_periods':    sorted(periods),
        'needs_strava_json': bool(previous_types),
    }
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
