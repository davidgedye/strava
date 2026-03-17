#!/usr/bin/env python3
"""
render_dzi.py — Render a Deep Zoom Image super-image for a given layout period
by compositing activity photos into their route bounding boxes.

Usage:
  python3 render_dzi.py [--period 2025] [--zip stravaExport_3_7_2026.zip]
                        [--layouts data/layouts] [--output data/dzi]
                        [--scale N]   # override auto-computed S
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pyvips
from PIL import Image, ImageOps


# ---------------------------------------------------------------------------
# Smart crop (face-aware)
# ---------------------------------------------------------------------------

def detect_faces(pil_img):
    """Return (anchor_x, anchor_y) centred on detected faces, or None."""
    np_rgb = np.array(pil_img.convert('RGB'))

    # Try mediapipe first — handles sunglasses, hats, non-frontal angles
    try:
        import mediapipe as mp
        detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.4)
        result = detector.process(np_rgb)
        detector.close()
        if result.detections:
            h, w = np_rgb.shape[:2]
            xs, ys = [], []
            for det in result.detections:
                bb = det.location_data.relative_bounding_box
                xs += [bb.xmin * w, (bb.xmin + bb.width)  * w]
                ys += [bb.ymin * h, (bb.ymin + bb.height) * h]
            return int((min(xs) + max(xs)) / 2), int((min(ys) + max(ys)) / 2)
    except Exception:
        pass

    # Fallback: OpenCV Haar cascade
    try:
        import cv2
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        cascade = cv2.CascadeClassifier(cascade_path)
        gray  = cv2.cvtColor(np_rgb, cv2.COLOR_RGB2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20))
        if len(faces) > 0:
            fx  = int(faces[:, 0].min())
            fy  = int(faces[:, 1].min())
            fx2 = int((faces[:, 0] + faces[:, 2]).max())
            fy2 = int((faces[:, 1] + faces[:, 3]).max())
            return (fx + fx2) // 2, (fy + fy2) // 2
    except Exception:
        pass

    return None


def smart_crop(pil_img, target_w, target_h):
    """Crop pil_img to target_w:target_h aspect ratio, centering on detected faces.
    Returns cropped PIL image (not yet resized)."""
    src_w, src_h = pil_img.size

    # Compute crop dimensions preserving aspect ratio
    src_ratio    = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        # Wider than needed — crop sides
        crop_h = src_h
        crop_w = round(src_h * target_ratio)
    else:
        # Taller than needed — crop top/bottom
        crop_w = src_w
        crop_h = round(src_w / target_ratio)

    # Default anchor: center
    anchor_x = src_w // 2
    anchor_y = src_h // 2

    face_anchor = detect_faces(pil_img)
    if face_anchor:
        anchor_x, anchor_y = face_anchor

    # Compute top-left of crop box, clamped to image bounds
    left = max(0, min(anchor_x - crop_w // 2, src_w - crop_w))
    top  = max(0, min(anchor_y - crop_h // 2, src_h - crop_h))

    return pil_img.crop((left, top, left + crop_w, top + crop_h))


# ---------------------------------------------------------------------------
# Build photo map from photos directory
# ---------------------------------------------------------------------------

def build_photo_map(photos_dir: Path) -> dict:
    """Return {activity_id_str: Path} for each {activity_id}.jpg in photos_dir."""
    if not photos_dir.exists():
        return {}
    return {p.stem: p for p in photos_dir.glob('*.jpg')}


# ---------------------------------------------------------------------------
# Compute bounding box for an activity in layout (CSS) coordinates
# ---------------------------------------------------------------------------

def coords_bbox(act, scale, cos_lat):
    """Return (min_x, min_y, max_x, max_y) in layout CSS coords, or None."""
    coords = act.get('coords')
    if coords:
        xs = [act['dx'] + c[0] * scale * cos_lat for c in coords]
        ys = [act['dy'] - c[1] * scale            for c in coords]
        return min(xs), min(ys), max(xs), max(ys)
    r = act.get('circle_radius')
    if r is not None:
        cr = r * scale
        return act['dx'] - cr, act['dy'] - cr, act['dx'] + cr, act['dy'] + cr
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='Render DZI for a Strava layout period')
    ap.add_argument('--period',     default='2025',         help='Period key (default: 2025)')
    ap.add_argument('--photos-dir', default='data/photos', help='Directory of {activity_id}.jpg files')
    ap.add_argument('--layouts',    default='data/layouts', help='Layouts directory')
    ap.add_argument('--output',     default='data/dzi',     help='Output directory')
    ap.add_argument('--scale',     type=int, default=None,              help='Override auto-computed S')
    ap.add_argument('--max-scale', type=int, default=68,               help='Cap auto-computed S (default: 68)')
    ap.add_argument('--landscape', action='store_true',                 help='Render landscape (-land) variant')
    args = ap.parse_args()

    period      = args.period
    photos_dir  = Path(args.photos_dir)
    layouts_dir = Path(args.layouts)
    output_dir  = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load layout JSON (portrait or landscape variant)
    layout_key  = period + ('-land' if args.landscape else '')
    layout_file = layouts_dir / f'{layout_key}.json'
    if not layout_file.exists():
        print(f'ERROR: layout file not found: {layout_file}', file=sys.stderr)
        sys.exit(1)
    with open(layout_file) as f:
        layout = json.load(f)

    scale   = layout.get('scale',   1000)
    cos_lat = layout.get('cos_lat', 0.674)
    canvas_w = layout.get('canvas_w', 393)
    canvas_h = layout.get('canvas_h', 710)
    activities = layout.get('activities', [])

    print(f'Period: {layout_key}  |  {len(activities)} activities in layout')

    # Load photo map
    print(f'Reading photo map from {photos_dir} ...')
    photo_map = build_photo_map(photos_dir)
    print(f'  {len(photo_map)} activities have photos')

    # Determine S (super-sampling scale factor)
    if args.scale is not None:
        S = args.scale
        print(f'S = {S} (overridden by --scale)')
    else:
        # Find the smallest max(bbox_w, bbox_h) among tracked (coords-only) activities with photos
        min_bbox_max_dim = None
        for act in activities:
            act_id = str(act.get('id', ''))
            if act_id not in photo_map:
                continue
            if act.get('circle_radius') is not None:
                continue  # skip circles for this calculation
            if not act.get('coords'):
                continue
            bbox = coords_bbox(act, scale, cos_lat)
            if bbox is None:
                continue
            min_x, min_y, max_x, max_y = bbox
            bw = max_x - min_x
            bh = max_y - min_y
            dim = max(bw, bh)
            if dim > 0 and (min_bbox_max_dim is None or dim < min_bbox_max_dim):
                min_bbox_max_dim = dim

        if min_bbox_max_dim is None or min_bbox_max_dim == 0:
            S = 4  # fallback
            print(f'WARNING: could not determine min bbox; defaulting S={S}')
        else:
            S = max(1, round(1200 / min_bbox_max_dim))
            print(f'Smallest tracked+photo bbox max-dim: {min_bbox_max_dim:.1f} CSS px  →  S = {S}')
        if args.max_scale is not None and S > args.max_scale:
            print(f'S capped at {args.max_scale} (--max-scale)')
            S = args.max_scale

    W = canvas_w * S
    H = canvas_h * S
    tile_size = 510
    # Rough tile count estimate (DZI pyramid)
    est_tiles = sum(
        math.ceil(W / (2**lv) / tile_size) * math.ceil(H / (2**lv) / tile_size)
        for lv in range(int(math.log2(max(W, H))) + 1)
    )
    print(f'Super-image: {W} × {H} px  |  estimated tile count: ~{est_tiles}')

    # Black background
    print('Creating black background ...')
    base = pyvips.Image.black(W, H, bands=3)

    placed = 0
    skipped = 0

    for i, act in enumerate(activities):
        if i > 0 and i % 10 == 0:
            print(f'  [{i}/{len(activities)}] placed={placed} skipped={skipped}')

        act_id = str(act.get('id', ''))
        if act_id not in photo_map:
            skipped += 1
            continue

        # Compute CSS bbox
        bbox = coords_bbox(act, scale, cos_lat)
        if bbox is None:
            skipped += 1
            continue

        min_x, min_y, max_x, max_y = bbox

        # Super-image pixel coords
        px0 = round(min_x * S)
        py0 = round(min_y * S)
        bw  = round((max_x - min_x) * S)
        bh  = round((max_y - min_y) * S)

        if bw < 4 or bh < 4:
            skipped += 1
            continue

        # Load photo
        try:
            pil_img = Image.open(photo_map[act_id])
            pil_img = ImageOps.exif_transpose(pil_img)
            pil_img = pil_img.convert('RGB')
        except Exception as exc:
            print(f'  WARN: could not load {photo_path}: {exc}')
            skipped += 1
            continue

        # Smart crop to aspect ratio bw:bh
        try:
            cropped = smart_crop(pil_img, bw, bh)
        except Exception as exc:
            print(f'  WARN: smart_crop failed for {act_id}: {exc}')
            skipped += 1
            continue

        # Convert cropped (native-resolution) image to pyvips — do NOT resize with PIL
        # first; let pyvips resize lazily during dzsave to avoid holding huge arrays.
        np_arr   = np.array(cropped, dtype=np.uint8)
        h_px, w_px, bands = np_arr.shape
        vips_img = pyvips.Image.new_from_memory(np_arr.tobytes(), w_px, h_px, bands, 'uchar')

        # Resize to target bbox dimensions — lazy in the pyvips pipeline
        vips_img = vips_img.resize(bw / w_px, vscale=bh / h_px)

        # Clamp so image fits in bounds
        px0 = max(0, min(px0, W - bw))
        py0 = max(0, min(py0, H - bh))

        base = base.insert(vips_img, px0, py0)
        placed += 1

    print(f'[{len(activities)}/{len(activities)}] placed={placed} skipped={skipped}')
    print(f'Saving DZI to {output_dir / layout_key} ...')

    # Create per-period output sub-directory so .dzi and _files/ live together.
    # Remove stale _files/ dir first so pyvips dzsave doesn't error on existing tiles.
    import shutil
    period_out = output_dir / layout_key
    period_out.mkdir(parents=True, exist_ok=True)
    stale_tiles = period_out / f'{layout_key}_files'
    if stale_tiles.exists():
        shutil.rmtree(stale_tiles)

    base.dzsave(
        str(period_out / layout_key),
        tile_size=510,
        overlap=1,
        layout='dz',
        suffix='.jpg[Q=85]',
    )

    print('Done.')


if __name__ == '__main__':
    main()
