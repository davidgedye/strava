#!/usr/bin/env python3
"""
Generate the PWA / Home Screen icon from a single activity's GPS route.

The route is simplified (GPS jitter removed), squared up to the street grid
(near-horizontal/vertical streets snapped onto shared lines, diagonals kept),
and drawn as a sharp-cornered green line on a dark blue map-grid background.

Usage:
    python3 make_icon.py <activity_id>          # fetches the track from R2 history
    python3 make_icon.py --track track.json     # [[lat, lng], ...] or a history JSON

Writes:
    icons/icon.svg        — vector icon (manifest)
    icons/icon-180.png    — apple-touch-icon (iOS Home Screen)
    icons/icon-192.png, icons/icon-512.png — manifest icons

Requires: Pillow, numpy
"""

import json
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

R2_BASE  = 'https://pub-235ce3251fcb4a3091c119ca67daa0d9.r2.dev/data/history'
OUT_DIR  = Path(__file__).parent / 'icons'

# ── Style (all in 1024×1024 icon units) ─────────────────────────────────────────
SIZE         = 1024
ROUTE_EXTENT = 640          # longest side of the route's bounding box
STROKE       = 32
ROUTE_COLOR  = '#4ade80'
BG_STOPS     = [(0.0, '#1e3a8a'), (0.6, '#172554'), (1.0, '#0b0d13')]
BG_CENTER    = (0.45, 0.40)  # radial gradient centre, as a fraction of SIZE
BG_RADIUS    = 0.75          # radial gradient radius, as a fraction of SIZE
GRID_STEP    = 64
GRID_COLOR   = '#7dd3fc'
GRID_OPACITY = 0.07
GRID_WIDTH   = 3

# ── Geometry tuning ─────────────────────────────────────────────────────────────
JITTER_TOL   = 10   # Ramer–Douglas–Peucker tolerance: wobble smaller than this is removed
AXIS_ANGLE   = 25   # segments within this many degrees of horizontal/vertical are squared
STREET_TOL   = 20   # parallel streets closer than this share one line
MIN_SEGMENT  = 18   # segments shorter than this are dropped


# ── Input ───────────────────────────────────────────────────────────────────────

def fetch_track(activity_id):
    """Fetch [lat, lng] pairs for an activity from the public R2 history."""
    with urllib.request.urlopen(f'{R2_BASE}/activity-index.json') as r:
        loc = json.load(r)[str(activity_id)]
    with urllib.request.urlopen(f'{R2_BASE}/{loc["year"]}/{loc["month"]:02d}/{activity_id}.json') as r:
        return track_from_json(json.load(r))


def track_from_json(data):
    """Accept a plain [[lat, lng], ...] list or a history activity JSON."""
    if isinstance(data, dict):
        return [[c[1], c[0]] for c in data['track']['coordinates']]  # GeoJSON is lng, lat
    return [[p[0], p[1]] for p in data]


# ── Geometry ────────────────────────────────────────────────────────────────────

def project(track):
    """Equirectangular projection, scaled and centred in the icon."""
    lat0 = sum(p[0] for p in track) / len(track)
    k = math.cos(math.radians(lat0))
    xy = [(lng * k, -lat) for lat, lng in track]
    xs = [x for x, _ in xy]
    ys = [y for _, y in xy]
    s = ROUTE_EXTENT / max(max(xs) - min(xs), max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [(SIZE / 2 + (x - cx) * s, SIZE / 2 + (y - cy) * s) for x, y in xy]


def seg_dist(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    l2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
    t = 0 if l2 == 0 else max(0, min(1, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / l2))
    return math.hypot(x - x1 - t * (x2 - x1), y - y1 - t * (y2 - y1))


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    dmax, i = max((seg_dist(p, pts[0], pts[-1]), i) for i, p in enumerate(pts[1:-1], 1))
    if dmax <= eps:
        return [pts[0], pts[-1]]
    return rdp(pts[:i + 1], eps)[:-1] + rdp(pts[i:], eps)


def simplify_loop(pts):
    """RDP on a closed loop: split at the point farthest from the start."""
    far = max(range(len(pts)), key=lambda i: math.dist(pts[0], pts[i]))
    return rdp(pts[:far + 1], JITTER_TOL)[:-1] + rdp(pts[far:] + [pts[0]], JITTER_TOL)[:-1]


def kind(a, b):
    ang = math.degrees(math.atan2(abs(b[1] - a[1]), abs(b[0] - a[0])))
    return 'H' if ang < AXIS_ANGLE else 'V' if ang > 90 - AXIS_ANGLE else 'D'


def cluster(vals):
    """Group nearby values into shared street lines."""
    vals = sorted(vals)
    if not vals:
        return []
    groups = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] < STREET_TOL:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def drop_short_and_collinear(pts):
    out = []
    for p in pts:
        if not out or math.dist(p, out[-1]) >= MIN_SEGMENT:
            out.append(p)
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if abs(cross) < 1e-6 * max(1, math.dist(a, c)) or math.dist(a, b) < MIN_SEGMENT:
                out.pop(i)
                changed = True
                break
    return out


def square_up(pts):
    """Snap near-horizontal/vertical segments onto shared street lines."""
    def segments(p):
        return [(i, (i + 1) % len(p), kind(p[i], p[(i + 1) % len(p)])) for i in range(len(p))]

    segs = segments(pts)
    h_lines = cluster([(pts[a][1] + pts[b][1]) / 2 for a, b, t in segs if t == 'H'])
    v_lines = cluster([(pts[a][0] + pts[b][0]) / 2 for a, b, t in segs if t == 'V'])
    snap = lambda v, lines: min(lines, key=lambda l: abs(l - v))

    r = [list(p) for p in pts]
    for _ in range(3):
        for a, b, t in segments(r):
            if t == 'H':
                r[a][1] = r[b][1] = snap((r[a][1] + r[b][1]) / 2, h_lines)
            elif t == 'V':
                r[a][0] = r[b][0] = snap((r[a][0] + r[b][0]) / 2, v_lines)
        r = drop_short_and_collinear(r)
    return [tuple(p) for p in r]


def route_shape(track):
    return square_up(simplify_loop(project(track)))


# ── Rendering ───────────────────────────────────────────────────────────────────

def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def write_svg(shape, path):
    stops = ''.join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in BG_STOPS)
    grid = ''.join(
        f'<line x1="{i}" y1="0" x2="{i}" y2="{SIZE}"/><line x1="0" y1="{i}" x2="{SIZE}" y2="{i}"/>'
        for i in range(GRID_STEP // 2, SIZE, GRID_STEP))
    d = 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in shape) + ' Z'
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">'
        f'<defs><radialGradient id="bg" cx="{BG_CENTER[0]:.0%}" cy="{BG_CENTER[1]:.0%}" r="{BG_RADIUS:.0%}">{stops}</radialGradient></defs>'
        f'<rect width="{SIZE}" height="{SIZE}" fill="url(#bg)"/>'
        f'<g stroke="{GRID_COLOR}" stroke-opacity="{GRID_OPACITY}" stroke-width="{GRID_WIDTH}">{grid}</g>'
        f'<path d="{d}" fill="none" stroke="{ROUTE_COLOR}" stroke-width="{STROKE}" '
        f'stroke-linejoin="miter" stroke-miterlimit="8"/></svg>\n')


def render_png(shape, size, ss=4):
    """Rasterise at ss× then downsample for anti-aliasing (no SVG renderer needed)."""
    n = size * ss
    f = n / SIZE

    # Radial gradient background
    yy, xx = np.mgrid[0:n, 0:n] / n
    t = np.clip(np.hypot(xx - BG_CENTER[0], yy - BG_CENTER[1]) / BG_RADIUS, 0, 1)
    offs = [o for o, _ in BG_STOPS]
    cols = np.array([hex_rgb(c) for _, c in BG_STOPS], float)
    rgb = np.stack([np.interp(t, offs, cols[:, i]) for i in range(3)], -1)
    img = Image.fromarray(rgb.astype(np.uint8), 'RGB')

    # Grid
    grid = Image.new('L', (n, n), 0)
    gd = ImageDraw.Draw(grid)
    w = max(1, round(GRID_WIDTH * f))
    for i in range(GRID_STEP // 2, SIZE, GRID_STEP):
        gd.line([(i * f, 0), (i * f, n)], fill=255, width=w)
        gd.line([(0, i * f), (n, i * f)], fill=255, width=w)
    img.paste(Image.new('RGB', (n, n), hex_rgb(GRID_COLOR)),
              mask=grid.point(lambda v: round(v * GRID_OPACITY)))

    # Route: each segment as a quad, plus a miter wedge at every corner
    mask = Image.new('L', (n, n), 0)
    md = ImageDraw.Draw(mask)
    half = STROKE * f / 2
    pts = [(x * f, y * f) for x, y in shape]
    m = len(pts)
    normals = []
    for i in range(m):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % m]
        L = math.hypot(x2 - x1, y2 - y1) or 1
        nx, ny = -(y2 - y1) / L * half, (x2 - x1) / L * half
        normals.append((nx, ny))
        md.polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], fill=255)
    for i in range(m):
        (px, py), (n1x, n1y), (n2x, n2y) = pts[i], normals[i - 1], normals[i]
        for sgn in (1, -1):
            a = (px + sgn * n1x, py + sgn * n1y)
            b = (px + sgn * n2x, py + sgn * n2y)
            bx, by = n1x + n2x, n1y + n2y
            bl = math.hypot(bx, by)
            if bl < 1e-9:
                continue
            cos_half = bl / (2 * half)
            if cos_half < 1 / 8:   # miter limit 8, as in the SVG
                md.polygon([(px, py), a, b], fill=255)
                continue
            ml = half / cos_half
            tip = (px + sgn * bx / bl * ml, py + sgn * by / bl * ml)
            md.polygon([(px, py), a, tip, b], fill=255)
    img.paste(Image.new('RGB', (n, n), hex_rgb(ROUTE_COLOR)), mask=mask)

    return img.resize((size, size), Image.LANCZOS)


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == '--track':
        track = track_from_json(json.loads(Path(args[1]).read_text()))
    elif len(args) == 1 and args[0].isdigit():
        track = fetch_track(args[0])
    else:
        sys.exit(__doc__)

    OUT_DIR.mkdir(exist_ok=True)
    shape = route_shape(track)
    write_svg(shape, OUT_DIR / 'icon.svg')
    for size in (180, 192, 512):
        render_png(shape, size).save(OUT_DIR / f'icon-{size}.png', optimize=True)
    print(f'{len(track)} track points → {len(shape)} corners; wrote {OUT_DIR}/')


if __name__ == '__main__':
    main()
