#!/usr/bin/env python3
"""
upload_dzi.py — Sync local data/dzi/ to Cloudflare R2 strava-data bucket.

Reads credentials from environment variables:
  R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT

Usage:
  R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_ENDPOINT=... python3 upload_dzi.py
  python3 upload_dzi.py [--dry-run] [--prefix data/dzi/2025]
"""

import argparse
import mimetypes
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

BUCKET      = 'strava-data'
LOCAL_ROOT  = Path('data/dzi')
REMOTE_ROOT = 'data/dzi'


def main():
    ap = argparse.ArgumentParser(description='Upload data/dzi/ to R2')
    ap.add_argument('--dry-run', action='store_true', help='Print what would be uploaded without uploading')
    ap.add_argument('--prefix',  default=None, help='Only upload files under this local path prefix (e.g. data/dzi/social)')
    args = ap.parse_args()

    endpoint = os.environ.get('R2_ENDPOINT')
    key_id   = os.environ.get('R2_ACCESS_KEY_ID')
    secret   = os.environ.get('R2_SECRET_ACCESS_KEY')

    if not all([endpoint, key_id, secret]):
        print('ERROR: set R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY', file=sys.stderr)
        sys.exit(1)

    s3 = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name='auto',
    )

    # Collect files to upload
    root = Path(args.prefix) if args.prefix else LOCAL_ROOT
    if not root.exists():
        print(f'ERROR: {root} does not exist', file=sys.stderr)
        sys.exit(1)

    files = sorted(root.rglob('*') if root.is_dir() else [root])
    files = [f for f in files if f.is_file()]

    print(f'{"[DRY RUN] " if args.dry_run else ""}Uploading {len(files)} files to s3://{BUCKET}/{REMOTE_ROOT}/ ...')

    uploaded = skipped = errors = 0
    for i, local in enumerate(files, 1):
        remote_key = REMOTE_ROOT + '/' + str(local.relative_to(LOCAL_ROOT))
        content_type = mimetypes.guess_type(str(local))[0] or 'application/octet-stream'
        if local.suffix == '.dzi':
            content_type = 'application/xml'

        if i % 500 == 0 or i == len(files):
            print(f'  [{i}/{len(files)}] uploaded={uploaded} errors={errors}')

        if args.dry_run:
            print(f'  WOULD upload {local} → {remote_key}')
            uploaded += 1
            continue

        try:
            s3.upload_file(
                str(local), BUCKET, remote_key,
                ExtraArgs={'ContentType': content_type},
            )
            uploaded += 1
        except (BotoCoreError, ClientError) as exc:
            print(f'  ERROR uploading {local}: {exc}', file=sys.stderr)
            errors += 1

    print(f'\nDone. uploaded={uploaded} errors={errors}')
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
