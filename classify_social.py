#!/usr/bin/env python3
"""
One-time backfill: stamp with_friends=true/false on all existing activity JSONs.

Applies social_classifier rules, then overrides from data/social_overrides.json.
Writes a summary to data/friends_stats.json.

Usage:
    python3 classify_social.py [data/history]
"""

import json
import sys
from pathlib import Path
from social_classifier import is_with_friends

RUN_TYPES = {'Run', 'Trail Run', 'Virtual Run', 'TrailRun', 'VirtualRun', 'Treadmill'}

def main():
    history_dir  = Path(sys.argv[1] if len(sys.argv) > 1 else 'data/history')
    overrides_file = Path('data/social_overrides.json')

    # Load override IDs
    overrides_true = set()
    overrides_false = set()
    if overrides_file.exists():
        data = json.loads(overrides_file.read_text())
        overrides_true = set(data.get('with_friends', []))
        overrides_false = set(data.get('not_friends', []))
    print(f'Loaded {len(overrides_true)} social overrides, {len(overrides_false)} not-social overrides')

    total = 0
    social = 0
    social_miles = 0.0
    changed = 0

    for p in sorted(history_dir.rglob('*.json')):
        if p.name == 'index.json':
            continue
        try:
            act = json.loads(p.read_text())
        except Exception:
            continue

        act_id = str(act.get('id', ''))
        name   = act.get('name', '')
        desc   = act.get('description') or ''

        # Classifier then overrides (not_friends beats with_friends)
        result = is_with_friends(name, desc) or (act_id in overrides_true)
        if act_id in overrides_false:
            result = False

        is_run = (act.get('type') in RUN_TYPES or act.get('sport_type') in RUN_TYPES)
        total += 1
        if result and is_run:
            social += 1
            social_miles += act.get('distance_mi', 0) or 0

        # Only rewrite if the field changed
        if act.get('with_friends') != result:
            act['with_friends'] = result
            p.write_text(json.dumps(act, separators=(',', ':')))
            changed += 1

    stats = {
        'friends_count': social,
        'friends_miles': round(social_miles, 1),
    }
    Path('data/friends_stats.json').write_text(json.dumps(stats, indent=2))

    print(f'Processed {total} activities: {social} social ({social_miles:.1f} mi)')
    print(f'Updated {changed} files')
    print(f'Wrote data/friends_stats.json: {stats}')

if __name__ == '__main__':
    main()
