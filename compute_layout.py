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

── Glacier packing ────────────────────────────────────────────────────────────

Routes are packed using "glacier" packing, which extends shelf packing with a
valley-fill step and a final row shuffle.

1. Shelf row assignment
   Items are sorted tallest-first and packed greedily into rows, each row as
   wide as the canvas allows.

2. Mountain ordering within rows
   Within each row, items are reordered so the tallest lands in the centre,
   with shorter items radiating outward symmetrically — like a mountain
   silhouette. Items are bottom-aligned within the row, leaving open space
   above the shorter items near the edges.

3. Glacier fill (valley filling)
   After placing each row's main items, the algorithm looks for opportunities
   to fill the open space above the shorter edge items on each side. For each
   side it computes a list of cumulative "open boxes" expanding inward:

     Box k spans items 0..k from the edge.
     Box height = row_height − max(h₀..hₖ)   (open space above the tallest
                                                item in the box's footprint)
     Box width  = cumulative width of items 0..k

   Boxes grow wider but shorter as k increases toward the taller centre items,
   so the centre item acts as a natural barrier that prevents left and right
   fills from encroaching on each other.

   The algorithm scans all remaining unplaced items for the one with the
   largest area that fits any box, then places it flush with the inner edge of
   the widest valid box (pushing it as far inward as possible). The outer gap
   left by that placement is then searched again, repeating until nothing more
   fits. At most a handful of fills occur per row.

4. Row shuffle
   After all rows are packed, their vertical order is randomised with a fixed
   seed. This eliminates the top-to-bottom size gradient that would otherwise
   result from the tallest-first packing order, while preserving each row's
   internal layout and the overall scale.

5. Scale binary search
   Steps 1–4 are wrapped in a 55-iteration binary search over css_scale
   (pixels per degree of latitude) to find the maximum scale at which
   everything fits within the canvas. Each halving narrows the bracket by
   2⁻⁵⁵ of its original width — effectively exact.
"""

import json
import math
import random
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

STROKE_CSS  = 1.5
PADDING_CSS = 2   # gap between routes
OUTER_CSS   = 8   # margin at canvas edges
CSS_MARGIN  = STROKE_CSS * 2 + PADDING_CSS   # 5 px per route

MAX_PTS = {'week': 500, 'month': 250, 'year': 200}

MILES_PER_DEG_LAT = 69.0   # approximate; used for circle radius calculation
COS_LAT_DEFAULT   = 0.674  # cos(47.6°) — Seattle-area average

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

HIKE_TYPES = {'Hike', 'Walk', 'Snowshoe'}


def is_run(act):
    return (act.get('sport_type') in RUN_TYPES or
            act.get('type')       in RUN_TYPES)


def is_hike(act):
    return (act.get('sport_type') in HIKE_TYPES or
            act.get('type')       in HIKE_TYPES)


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


def load_all_hikes(history_dir):
    """Load every hike/walk/snowshoe activity (tracked or not), sorted by date ascending."""
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
                if is_hike(data):
                    result.append(data)
    return sorted(result, key=lambda a: a['date'])


# ── Route / circle geometry ────────────────────────────────────────────────────

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


def extract_circle(act):
    """For untracked runs: circular placeholder whose circumference equals the distance."""
    dist     = act.get('distance_mi') or 0
    r_deg    = dist / (2 * math.pi * MILES_PER_DEG_LAT)
    return {
        'id':            str(act['id']),
        'name':          act.get('name', ''),
        'date':          act['date'],
        'cos_lat':       COS_LAT_DEFAULT,
        'span_lat':      2 * r_deg,
        'span_lng':      2 * r_deg / COS_LAT_DEFAULT,  # makes bounding box square
        'circle_radius': r_deg,
        'distance_mi':   dist,
    }


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
    cur_row, cur_w = [], OUTER_CSS
    for i in order:
        w, _ = _css_size(routes[i], css_scale)
        if cur_row and cur_w + w > cw - OUTER_CSS:
            rows.append(cur_row)
            cur_row, cur_w = [], OUTER_CSS
        if cur_w + w > cw - OUTER_CSS:   # too wide even on a fresh row
            return
        cur_row.append(i)
        cur_w += w + PADDING_CSS
    if cur_row:
        rows.append(cur_row)

    # ── 2. Check total height fits ─────────────────────────────────────────────
    row_h = [max(_css_size(routes[i], css_scale)[1] for i in row) for row in rows]
    if OUTER_CSS + sum(h + PADDING_CSS for h in row_h) + OUTER_CSS > ch:
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
    y = OUTER_CSS
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


# ── Glacier packing ────────────────────────────────────────────────────────────

def _glacier_css(items, css_scale, cw=CANVAS_W, ch=CANVAS_H, rows_out=None):
    """
    Glacier packing. Yields (i, cx, cy) for every item, or nothing on failure.
    If rows_out is a list, appends (y_top, row_h, [item_indices]) per row.
    """
    n = len(items)
    placed = [False] * n
    queue  = sorted(range(n), key=lambda i: -items[i]['span_lat'])

    positions = {}
    y_cursor  = OUTER_CSS

    while queue:
        placed_before = set(positions)

        # ── Select items for this shelf row (greedy, tallest first) ──────────
        row_indices, leftover = [], []
        used_w = OUTER_CSS
        for i in queue:
            iw, _ = _css_size(items[i], css_scale)
            if not row_indices or used_w + iw + PADDING_CSS <= cw - OUTER_CSS:
                row_indices.append(i)
                used_w += iw + PADDING_CSS
            else:
                leftover.append(i)

        if not row_indices:
            break

        row_h = max(_css_size(items[i], css_scale)[1] for i in row_indices)
        if y_cursor + row_h + OUTER_CSS > ch:
            break

        # ── Mountain-order within row, bottom-aligned ─────────────────────
        mountain = _mountain(sorted(row_indices, key=lambda i: -items[i]['span_lat']))
        total_row_w = (sum(_css_size(items[i], css_scale)[0] for i in mountain)
                       + PADDING_CSS * (len(mountain) - 1))
        x_left  = (cw - total_row_w) / 2
        x_right = x_left + total_row_w

        x = x_left
        item_positions = []   # (idx, x_left, width, height)
        for i in mountain:
            iw, ih = _css_size(items[i], css_scale)
            positions[i] = (x + iw / 2, y_cursor + row_h - ih / 2)
            placed[i] = True
            item_positions.append((i, x, iw, ih))
            x += iw + PADDING_CSS

        # ── Glacier fill: inside-out, one pass per side ───────────────────
        candidates = [i for i in leftover if not placed[i]]

        for side in ('left', 'right'):
            edge_items = item_positions if side == 'left' else list(reversed(item_positions))

            all_boxes = []
            cum_w, max_h = 0, 0
            for k, (_, _, w_k, h_k) in enumerate(edge_items):
                cum_w += w_k + (PADDING_CSS if k < len(edge_items) - 1 else 0)
                max_h  = max(max_h, h_k)
                box_h  = row_h - max_h
                if box_h >= PADDING_CSS * 2:
                    all_boxes.append((cum_w, box_h))

            available_w = all_boxes[-1][0] if all_boxes else 0

            while available_w > PADDING_CSS * 2 and candidates and all_boxes:
                boxes = [(bw, bh) for bw, bh in all_boxes if bw <= available_w]
                if not boxes:
                    break

                best_j, best_area, best_bw = None, 0, None
                for j in candidates:
                    jw, jh = _css_size(items[j], css_scale)
                    valid = [bw for bw, bh in boxes
                             if jw + PADDING_CSS <= bw and jh + PADDING_CSS <= bh]
                    if not valid:
                        continue
                    area = jw * jh
                    if area > best_area:
                        best_area, best_j, best_bw = area, j, max(valid)

                if best_j is None:
                    break

                jw, jh = _css_size(items[best_j], css_scale)
                cx = (x_left  + best_bw - jw / 2) if side == 'left' else \
                     (x_right - best_bw + jw / 2)
                positions[best_j] = (cx, y_cursor + jh / 2)
                placed[best_j] = True
                candidates = [i for i in candidates if i != best_j]
                leftover   = [i for i in leftover   if i != best_j]
                available_w = best_bw - jw - PADDING_CSS

        if rows_out is not None:
            rows_out.append((y_cursor, row_h,
                             [i for i in positions if i not in placed_before]))
        y_cursor += row_h + PADDING_CSS  # inter-row gap
        queue = leftover

    if len(positions) == n:
        for i, (cx, cy) in positions.items():
            yield i, cx, cy


def _glacier_fits(items, css_scale, cw=CANVAS_W, ch=CANVAS_H):
    return sum(1 for _ in _glacier_css(items, css_scale, cw, ch)) == len(items)


def _max_glacier_scale(items, cw=CANVAS_W, ch=CANVAS_H):
    if not items:
        return 50_000.0
    lo, hi = 1.0, 50_000.0
    for _ in range(55):
        mid = (lo + hi) / 2
        if _glacier_fits(items, mid, cw, ch):
            lo = mid
        else:
            hi = mid
    return lo


def _shuffle_rows(positions, rows, seed):
    """Shuffle row order, preserving each item's position relative to its row top."""
    shuffled = rows[:]
    random.Random(seed).shuffle(shuffled)
    new_positions = list(positions)
    y = OUTER_CSS
    for old_y_top, row_h, indices in shuffled:
        for i in indices:
            old_cx, old_cy = positions[i]
            new_positions[i] = (old_cx, y + (old_cy - old_y_top))
        y += row_h + PADDING_CSS
    return new_positions


def glacier_positions(items, css_scale, cw=CANVAS_W, ch=CANVAS_H, seed=42):
    """Pack items with glacier algorithm and shuffle row order. Returns position list."""
    rows = []
    result = [None] * len(items)
    for i, cx, cy in _glacier_css(items, css_scale, cw, ch, rows_out=rows):
        result[i] = (cx, cy)
    for i, v in enumerate(result):
        if v is None:
            result[i] = (cw / 2, ch / 2)
    if rows:
        result = _shuffle_rows(result, rows, seed)
    return result


# ── Period layout ──────────────────────────────────────────────────────────────

def compute_layout(runs, kind, canvas_w=CANVAS_W, canvas_h=CANVAS_H, seed=42):
    """
    runs : all runs in period (tracked + untracked)
    kind : 'week' | 'month' | 'year'  (controls point-count simplification)
    Returns dict ready for JSON.
    """
    tracked   = [a for a in runs if a.get('has_track')]
    untracked = [a for a in runs if not a.get('has_track') and (a.get('distance_mi') or 0) > 0]

    routes  = [extract_route(a, MAX_PTS[kind]) for a in tracked]
    circles = [extract_circle(a) for a in untracked]

    # Merge and sort by date so colour ranking spans both tracked and untracked
    items = sorted(routes + circles, key=lambda r: r['date'])

    if not items:
        return {'scale': 1000.0, 'cos_lat': COS_LAT_DEFAULT, 'total_miles': 0,
                'canvas_w': canvas_w, 'canvas_h': canvas_h, 'activities': []}

    n = len(items)
    for rank, item in enumerate(items):
        item['color'] = route_color(rank, n)

    css_scale = _max_glacier_scale(items, canvas_w, canvas_h)
    positions = glacier_positions(items, css_scale, canvas_w, canvas_h, seed=seed)

    avg_cos = sum(r['cos_lat'] for r in items) / n
    out = []
    for item, (dx, dy) in zip(items, positions):
        entry = {
            'id':    item['id'],
            'name':  item['name'],
            'date':  item['date'],
            'color': item['color'],
            'dx':    round(dx, 1),
            'dy':    round(dy, 1),
        }
        if 'circle_radius' in item:
            entry['circle_radius'] = round(item['circle_radius'], 4)
        else:
            entry['coords'] = [[round(c[0], 4), round(c[1], 4)] for c in item['rel_coords']]
        entry['cos_lat'] = round(item['cos_lat'], 6)
        if item.get('distance_mi') is not None:
            entry['distance_mi'] = round(item['distance_mi'])
        out.append(entry)

    total_miles = sum(a.get('distance_mi') or 0 for a in runs)
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
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    force = '--force' in sys.argv
    history_dir = args[0] if len(args) > 0 else 'data/history'
    output_dir  = args[1] if len(args) > 1 else 'data/layouts'

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    cur = current_periods()
    print(f"Current: week from {cur['week_start'].date()}, "
          f"month={cur['month']}, year={cur['year']}", file=sys.stderr)

    # Load all runs (tracked + untracked); compute_layout handles the split
    print("Loading all run activities…", file=sys.stderr)
    t0 = time.time()
    all_runs = load_all_runs(history_dir)
    n_tracked = sum(1 for a in all_runs if a.get('has_track'))
    print(f"  {len(all_runs)} runs total, {n_tracked} with GPS track, "
          f"in {time.time()-t0:.1f}s", file=sys.stderr)

    # Group by month and year — always include current periods even if empty
    by_month = {cur['month']: []}
    by_year  = {cur['year']:  []}
    for act in all_runs:
        dt = parse_dt(act['date'])
        mk = f"{dt.year}-{dt.month:02d}"
        yk = str(dt.year)
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
        week_runs = [a for a in all_runs
                     if cur['week_start'] <= parse_dt(a['date']) < cur['now']]
        t0 = time.time()
        data = compute_layout(week_runs, 'week', cw, ch, seed='week')
        (out / f'week{suffix}.json').write_text(json.dumps(data, separators=(',', ':')))
        print(f"  {sum(1 for a in week_runs if a.get('has_track'))} tracked / {len(week_runs)} total, "
              f"{time.time()-t0:.1f}s", file=sys.stderr)

        # ── Months ────────────────────────────────────────────────────────────
        for mk in all_month_keys:
            is_current = (mk == cur['month'])
            dest = out / f'{mk}{suffix}.json'
            if not is_current and dest.exists() and not force:
                print(f"\n── {mk}{suffix} … skipped (cached)", file=sys.stderr)
                continue
            runs = ([a for a in by_month.get(mk, []) if parse_dt(a['date']) < cur['now']]
                    if is_current else by_month.get(mk, []))
            print(f"\n── {mk}{suffix} …", file=sys.stderr)
            t0 = time.time()
            data = compute_layout(runs, 'month', cw, ch, seed=mk)
            dest.write_text(json.dumps(data, separators=(',', ':')))
            print(f"  {sum(1 for a in runs if a.get('has_track'))} tracked / {len(runs)} total, "
                  f"{time.time()-t0:.1f}s", file=sys.stderr)

        # ── Years ─────────────────────────────────────────────────────────────
        for yk in all_year_keys:
            is_current = (yk == cur['year'])
            dest = out / f'{yk}{suffix}.json'
            if not is_current and dest.exists() and not force:
                print(f"\n── {yk}{suffix} … skipped (cached)", file=sys.stderr)
                continue
            runs = ([a for a in by_year.get(yk, []) if parse_dt(a['date']) < cur['now']]
                    if is_current else by_year.get(yk, []))
            print(f"\n── {yk}{suffix} …", file=sys.stderr)
            t0 = time.time()
            data = compute_layout(runs, 'year', cw, ch, seed=yk)
            dest.write_text(json.dumps(data, separators=(',', ':')))
            print(f"  {sum(1 for a in runs if a.get('has_track'))} tracked / {len(runs)} total, "
                  f"{time.time()-t0:.1f}s", file=sys.stderr)

        # ── Friends (all-time) — 2.5× canvas so routes aren't microscopic ───
        friends_runs  = [a for a in all_runs if a.get('with_friends')]
        friends_count = len(friends_runs)
        dest_social   = out / f'social{suffix}.json'
        cached_ok = False
        if not force and dest_social.exists():
            try:
                if json.loads(dest_social.read_text()).get('friend_count') == friends_count:
                    cached_ok = True
            except Exception:
                pass
        if cached_ok:
            print(f"\n── social{suffix} … skipped (cached, {friends_count} friend runs)",
                  file=sys.stderr)
        else:
            print(f"\n── social{suffix} …", file=sys.stderr)
            fcw, fch = round(cw * 2.5), round(ch * 2.5)
            t0 = time.time()
            data = compute_layout(friends_runs, 'year', fcw, fch, seed='social')
            data['friend_count'] = friends_count
            dest_social.write_text(json.dumps(data, separators=(',', ':')))
            print(f"  {sum(1 for a in friends_runs if a.get('has_track'))} tracked / "
                  f"{friends_count} total, canvas {fcw}×{fch}, {time.time()-t0:.1f}s",
                  file=sys.stderr)

        # ── Hikes (all-time) — 2.5× canvas so routes aren't microscopic ─────
        hike_acts   = load_all_hikes(history_dir)
        hike_count  = len(hike_acts)
        dest_hikes  = out / f'hikes{suffix}.json'
        cached_ok = False
        if not force and dest_hikes.exists():
            try:
                if json.loads(dest_hikes.read_text()).get('hike_count') == hike_count:
                    cached_ok = True
            except Exception:
                pass
        if cached_ok:
            print(f"\n── hikes{suffix} … skipped (cached, {hike_count} hikes)",
                  file=sys.stderr)
        else:
            print(f"\n── hikes{suffix} …", file=sys.stderr)
            hcw, hch = round(cw * 2.5), round(ch * 2.5)
            t0 = time.time()
            data = compute_layout(hike_acts, 'year', hcw, hch, seed='hikes')
            data['hike_count'] = hike_count
            dest_hikes.write_text(json.dumps(data, separators=(',', ':')))
            print(f"  {sum(1 for a in hike_acts if a.get('has_track'))} tracked / "
                  f"{hike_count} total, canvas {hcw}×{hch}, {time.time()-t0:.1f}s",
                  file=sys.stderr)

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
