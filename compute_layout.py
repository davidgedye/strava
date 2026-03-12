#!/usr/bin/env python3
"""
compute_layout.py — Pre-compute route display layouts for all periods.

Outputs data/layouts/ directory containing:
  index.json          — list of available months/years + current-period keys
  week.json           — current week
  YYYY-MM.json        — each month that has tracked activities
  YYYY.json           — each year that has tracked activities
  *-land.json         — landscape variants of the above (800×400)

Usage:
    python3 compute_layout.py [data/history] [data/layouts]
"""

import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Canvas constants ───────────────────────────────────────────────────────────

CANVAS_W = 393    # iPhone 16 portrait (CSS px)
CANVAS_H = 710    # drawable area between title strip and bottom edge

# Landscape — 2:1, midpoint between laptop 16:9 (1.78) and phone sideways (2.17)
CANVAS_W_LAND = 800
CANVAS_H_LAND = 400

STROKE_CSS  = 3
PADDING_CSS = 6
CSS_MARGIN  = STROKE_CSS * 2 + PADDING_CSS   # 12 px per route

MAX_PTS = {'week': 500, 'month': 250, 'year': 200}

# ── Colour ─────────────────────────────────────────────────────────────────────

L_OLD = 22    # lightness % for oldest activity
L_NEW = 95    # lightness % for newest activity


def _lum_to_hex(l):
    v = round(l / 100 * 255)
    return '#{0:02x}{0:02x}{0:02x}'.format(v)


def route_color(rank, total):
    """rank=0 oldest → rank=total-1 newest."""
    t = rank / (total - 1) if total > 1 else 1.0
    return _lum_to_hex(L_OLD + t * (L_NEW - L_OLD))


# ── Date utilities ─────────────────────────────────────────────────────────────

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


def parse_dt(s):
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Activity loading ───────────────────────────────────────────────────────────

# Matches incremental_update.py's SPORT_TYPE_MAP output and RUN_TYPES.
# Also covers raw API sport_type values in case sport_type field is present.
RUN_TYPES = {'Run', 'Trail Run', 'Virtual Run',          # normalised (stored)
             'TrailRun', 'VirtualRun', 'Treadmill'}      # raw API sport_type


def is_run(act):
    return (act.get('sport_type') in RUN_TYPES or
            act.get('type')       in RUN_TYPES)


def load_all_runs(history_dir):
    """Load every run activity (tracked or not), sorted by date ascending."""
    history = Path(history_dir)
    result = []
    for year_dir in history.iterdir():
        if not year_dir.is_dir():
            continue
        try:
            int(year_dir.name)
        except ValueError:
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue
            for f in month_dir.iterdir():
                if f.name == 'index.json' or f.suffix != '.json':
                    continue
                try:
                    data = json.loads(f.read_text())
                except Exception:
                    continue
                if is_run(data):
                    result.append(data)
    return sorted(result, key=lambda a: a['date'])


# ── Route geometry ─────────────────────────────────────────────────────────────

def extract_route(act, max_pts):
    raw = act['track']['coordinates']
    if len(raw) > max_pts:
        step = len(raw) / max_pts
        raw = [raw[int(i * step)] for i in range(max_pts)]

    lngs = [c[0] for c in raw]
    lats  = [c[1] for c in raw]
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats),  max(lats)
    center_lng = (min_lng + max_lng) / 2
    center_lat = (min_lat + max_lat) / 2

    result = {
        'id':         str(act['id']),
        'name':       act.get('name', ''),
        'date':       act['date'],
        'center_lng': center_lng,
        'center_lat': center_lat,
        'cos_lat':    math.cos(math.radians(center_lat)),
        'span_lng':   max_lng - min_lng,
        'span_lat':   max_lat - min_lat,
        'rel_coords': [[c[0] - center_lng, c[1] - center_lat] for c in raw],
    }
    if act.get('distance_mi') is not None:
        result['distance_mi'] = act['distance_mi']
    return result


# ── Shelf packing ──────────────────────────────────────────────────────────────

def _css_size(r, css_scale):
    w = max(r['span_lng'] * r['cos_lat'] * css_scale + CSS_MARGIN, CSS_MARGIN)
    h = max(r['span_lat']               * css_scale + CSS_MARGIN, CSS_MARGIN)
    return w, h


def _mountain(items_desc):
    """Reorder a tallest-first list so the tallest lands in the centre,
    with shorter items radiating outward symmetrically to the ends."""
    n = len(items_desc)
    if n == 0:
        return []
    result = [None] * n
    mid = n // 2
    pos_order = [mid]
    l, r = mid - 1, mid + 1
    while l >= 0 or r < n:
        if l >= 0:
            pos_order.append(l); l -= 1
        if r < n:
            pos_order.append(r); r += 1
    for item, pos in zip(items_desc, pos_order):
        result[pos] = item
    return result


def _shelf_css(routes, css_scale, cw=CANVAS_W, ch=CANVAS_H):
    # ── 1. Assign routes to rows (greedy, tallest-first) ──────────────────────
    order = sorted(range(len(routes)), key=lambda i: -routes[i]['span_lat'])
    rows = []
    cur_row, cur_w = [], PADDING_CSS
    for i in order:
        w, _ = _css_size(routes[i], css_scale)
        if cur_row and cur_w + w > cw - PADDING_CSS:
            rows.append(cur_row)
            cur_row, cur_w = [], PADDING_CSS
        if cur_w + w > cw - PADDING_CSS:   # too wide even on a fresh row
            return
        cur_row.append(i)
        cur_w += w + PADDING_CSS
    if cur_row:
        rows.append(cur_row)

    # ── 2. Check total height fits ─────────────────────────────────────────────
    row_h = [max(_css_size(routes[i], css_scale)[1] for i in row) for row in rows]
    if PADDING_CSS + sum(h + PADDING_CSS for h in row_h) > ch:
        return

    # ── 3. Mountain-order items within each row (tallest centre, short ends) ───
    ordered_rows = [_mountain(sorted(row, key=lambda i: -routes[i]['span_lat']))
                    for row in rows]

    # ── 4. Mountain-order the rows (tallest row in middle, short rows top/bot) ─
    row_sequence = _mountain(sorted(range(len(ordered_rows)),
                                    key=lambda r: -row_h[r]))

    # ── 5. Emit centre positions (each row horizontally centred) ─────────────
    row_widths = [sum(_css_size(routes[i], css_scale)[0] for i in row)
                  + PADDING_CSS * (len(row) - 1)
                  for row in ordered_rows]
    y = PADDING_CSS
    for r in row_sequence:
        x = (cw - row_widths[r]) / 2
        for i in ordered_rows[r]:
            w, _ = _css_size(routes[i], css_scale)
            yield i, x + w / 2, y + row_h[r] / 2
            x += w + PADDING_CSS
        y += row_h[r] + PADDING_CSS


def shelf_fits(routes, css_scale, cw=CANVAS_W, ch=CANVAS_H):
    return sum(1 for _ in _shelf_css(routes, css_scale, cw, ch)) == len(routes)


def max_shelf_css_scale(routes, cw=CANVAS_W, ch=CANVAS_H):
    if not routes:
        return 50_000.0
    lo, hi = 1.0, 50_000.0
    for _ in range(55):
        mid = (lo + hi) / 2
        if shelf_fits(routes, mid, cw, ch):
            lo = mid
        else:
            hi = mid
    return lo


def shelf_positions_css(routes, css_scale, cw=CANVAS_W, ch=CANVAS_H):
    result = [None] * len(routes)
    for i, dx, dy in _shelf_css(routes, css_scale, cw, ch):
        result[i] = (dx, dy)
    for i, v in enumerate(result):
        if v is None:
            result[i] = (cw / 2, ch / 2)
    return result


# ── Period layout ──────────────────────────────────────────────────────────────

def compute_layout(activities, kind, canvas_w=CANVAS_W, canvas_h=CANVAS_H,
                   all_runs=None):
    """
    kind     : 'week' | 'month' | 'year'  (controls point-count simplification)
    all_runs : all runs in period (tracked + untracked) for mileage total;
               defaults to activities if not supplied
    Returns dict ready for JSON.
    """
    routes = [extract_route(a, MAX_PTS[kind]) for a in activities]

    if not routes:
        return {'scale': 1000.0, 'cos_lat': 0.674, 'total_miles': 0, 'activities': []}

    n = len(routes)
    for rank, r in enumerate(routes):
        r['color'] = route_color(rank, n)

    css_scale = max_shelf_css_scale(routes, canvas_w, canvas_h)
    positions = shelf_positions_css(routes, css_scale, canvas_w, canvas_h)

    avg_cos = sum(r['cos_lat'] for r in routes) / n
    out = []
    for r, (dx, dy) in zip(routes, positions):
        entry = {
            'id':     r['id'],
            'name':   r['name'],
            'date':   r['date'],
            'color':  r['color'],
            'dx':     round(dx, 1),
            'dy':     round(dy, 1),
            'coords': [[round(c[0], 6), round(c[1], 6)] for c in r['rel_coords']],
        }
        if r.get('distance_mi') is not None:
            entry['distance_mi'] = round(r['distance_mi'])
        out.append(entry)

    mile_source = all_runs if all_runs is not None else activities
    total_miles = sum(a.get('distance_mi') or 0 for a in mile_source)
    return {
        'scale':       round(css_scale, 4),
        'cos_lat':     round(avg_cos, 6),
        'total_miles': round(total_miles),
        'canvas_w':    canvas_w,
        'canvas_h':    canvas_h,
        'activities':  out,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    history_dir = sys.argv[1] if len(sys.argv) > 1 else 'data/history'
    output_dir  = sys.argv[2] if len(sys.argv) > 2 else 'data/layouts'

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    cur = current_periods()
    print(f"Current: week from {cur['week_start'].date()}, "
          f"month={cur['month']}, year={cur['year']}", file=sys.stderr)

    # Load all runs (for mileage totals) and tracked subset (for layout)
    print("Loading all run activities…", file=sys.stderr)
    t0 = time.time()
    all_runs = load_all_runs(history_dir)
    all_acts = [a for a in all_runs if a.get('has_track')]
    print(f"  {len(all_runs)} runs total, {len(all_acts)} with GPS track, "
          f"in {time.time()-t0:.1f}s", file=sys.stderr)

    # Group by month and year — always include current periods even if empty
    # by_*: tracked only (for layout);  miles_by_*: all runs (for totals)
    by_month       = {cur['month']: []}
    by_year        = {cur['year']:  []}
    miles_by_month = {cur['month']: []}
    miles_by_year  = {cur['year']:  []}
    for act in all_runs:
        dt = parse_dt(act['date'])
        mk = f"{dt.year}-{dt.month:02d}"
        yk = str(dt.year)
        miles_by_month.setdefault(mk, []).append(act)
        miles_by_year.setdefault(yk,  []).append(act)
        if act.get('has_track'):
            by_month.setdefault(mk, []).append(act)
            by_year.setdefault(yk,  []).append(act)

    all_month_keys = sorted(by_month.keys(), reverse=True)
    all_year_keys  = sorted(by_year.keys(),  reverse=True)

    # Canvas configs: (label, canvas_w, canvas_h, file_suffix)
    configs = [
        ('portrait',  CANVAS_W,      CANVAS_H,      ''),
        ('landscape', CANVAS_W_LAND, CANVAS_H_LAND, '-land'),
    ]

    for orient, cw, ch, suffix in configs:
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Layout: {orient}  ({cw}×{ch})", file=sys.stderr)

        # ── Week ──────────────────────────────────────────────────────────────
        print(f"\n── week{suffix} …", file=sys.stderr)
        week_acts = [a for a in all_acts
                     if cur['week_start'] <= parse_dt(a['date']) < cur['now']]
        week_runs = [a for a in all_runs
                     if cur['week_start'] <= parse_dt(a['date']) < cur['now']]
        t0 = time.time()
        data = compute_layout(week_acts, 'week', cw, ch, all_runs=week_runs)
        (out / f'week{suffix}.json').write_text(json.dumps(data, separators=(',', ':')))
        print(f"  {len(week_acts)} tracked / {len(week_runs)} total, "
              f"{time.time()-t0:.1f}s", file=sys.stderr)

        # ── Months ────────────────────────────────────────────────────────────
        for mk in all_month_keys:
            is_current = (mk == cur['month'])
            dest = out / f'{mk}{suffix}.json'
            if not is_current and dest.exists():
                print(f"\n── {mk}{suffix} … skipped (cached)", file=sys.stderr)
                continue
            acts = ([a for a in by_month.get(mk, []) if parse_dt(a['date']) < cur['now']]
                    if is_current else by_month.get(mk, []))
            runs = ([a for a in miles_by_month.get(mk, []) if parse_dt(a['date']) < cur['now']]
                    if is_current else miles_by_month.get(mk, []))
            print(f"\n── {mk}{suffix} …", file=sys.stderr)
            t0 = time.time()
            data = compute_layout(acts, 'month', cw, ch, all_runs=runs)
            dest.write_text(json.dumps(data, separators=(',', ':')))
            print(f"  {len(acts)} tracked / {len(runs)} total, "
                  f"{time.time()-t0:.1f}s", file=sys.stderr)

        # ── Years ─────────────────────────────────────────────────────────────
        for yk in all_year_keys:
            is_current = (yk == cur['year'])
            dest = out / f'{yk}{suffix}.json'
            if not is_current and dest.exists():
                print(f"\n── {yk}{suffix} … skipped (cached)", file=sys.stderr)
                continue
            acts = ([a for a in by_year.get(yk, []) if parse_dt(a['date']) < cur['now']]
                    if is_current else by_year.get(yk, []))
            runs = ([a for a in miles_by_year.get(yk, []) if parse_dt(a['date']) < cur['now']]
                    if is_current else miles_by_year.get(yk, []))
            print(f"\n── {yk}{suffix} …", file=sys.stderr)
            t0 = time.time()
            data = compute_layout(acts, 'year', cw, ch, all_runs=runs)
            dest.write_text(json.dumps(data, separators=(',', ':')))
            print(f"  {len(acts)} tracked / {len(runs)} total, "
                  f"{time.time()-t0:.1f}s", file=sys.stderr)

        # ── Friends (all-time) — 2.5× canvas so routes aren't microscopic ───
        print(f"\n── friends{suffix} …", file=sys.stderr)
        friends_runs = [a for a in all_runs if a.get('with_friends')]
        friends_acts = [a for a in friends_runs if a.get('has_track')]
        fcw, fch = round(cw * 2.5), round(ch * 2.5)
        t0 = time.time()
        data = compute_layout(friends_acts, 'year', fcw, fch, all_runs=friends_runs)
        (out / f'friends{suffix}.json').write_text(json.dumps(data, separators=(',', ':')))
        print(f"  {len(friends_acts)} tracked / {len(friends_runs)} total, "
              f"canvas {fcw}×{fch}, {time.time()-t0:.1f}s", file=sys.stderr)

    # ── Index ─────────────────────────────────────────────────────────────────
    index = {
        'current_month': cur['month'],
        'current_year':  cur['year'],
        'months': all_month_keys,
        'years':  all_year_keys,
    }
    (out / 'index.json').write_text(json.dumps(index, separators=(',', ':')))
    print(f"\nWrote {output_dir}/", file=sys.stderr)


if __name__ == '__main__':
    main()
