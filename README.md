# Strava Running Dashboard

A personal running dashboard, hosted on GitHub Pages. A daily GitHub Action pulls data from the Strava API, processes it, and uploads everything to Cloudflare R2. The HTML/JS is served from GitHub Pages; all data is fetched from R2 at runtime. There is no backend.

## Pages

| Page | URL | Description |
|---|---|---|
| **Progress** | `index.html` | Weekly / monthly / yearly distance vs. goals, with fireworks on completion |
| **Routes** | `routes.html` | Full-screen canvas of GPS route outlines, packed with boxcraft, with a Deep Zoom photo background |
| **Lifetime** | `planet.html` | Cumulative lifetime distance visualisation |

`routes.html` accepts a `?period=` query parameter:
- `week` — current rolling week
- `YYYY-MM` — a specific month
- `YYYY` — a full year
- `social` — runs inferred to have been done with other people (frozen as of 6/16/26; direct URL only)
- `hikes` — all hikes, walks, and snowshoes (frozen as of 6/16/26; direct URL only)

The routes page auto-detects portrait vs landscape and loads the appropriate layout.

## Architecture

```
GitHub Actions (daily)
  └─ fetch-strava.sh        ← Strava API → summary JSON (week/month/year totals)
  └─ incremental_update.py  ← Strava API → per-activity history JSON + photos
  └─ compute_layout.py      ← history/ + layouts/ → boxcraft-packed route layouts
  └─ render_dzi.py          ← photos/ → Deep Zoom Image tiles
  └─ aws s3 sync → Cloudflare R2 (strava-data bucket)

GitHub Pages
  └─ index.html / routes.html / planet.html
       └─ fetch data at runtime from R2 public URL
```

All data lives in Cloudflare R2 under `data/`:

| Path | Contents |
|---|---|
| `data/history/{id}.json` | Per-activity JSON (GPS track, distance, photos, etc.) |
| `data/layouts/{period}.json` | Pre-computed route layout for a period |
| `data/photos/{id}.jpg` | Activity photos |
| `data/dzi/{period}/` | Deep Zoom Image tiles for photo background |

The git repo contains only code — no data files are committed.

## Daily Workflow

The `update-if-new.yml` workflow runs three times daily (10am, noon, and 6pm PST) and does the following:

1. **Download** `history/`, `layouts/`, and `photos/` from R2
2. **Fetch** current week/month/year summaries via `fetch-strava.sh`
3. **Update history** — `incremental_update.py` adds JSON for any new activities and downloads their photos
4. **Compute layouts** — `compute_layout.py` regenerates layouts for the current week/month/year (historical periods are cached)
5. **Render DZI** — `render_dzi.py` smart-crops each activity photo to the aspect ratio of its route's bounding box, then renders Deep Zoom tiles (512 px tiles, 1 px overlap) for the current week/month/year

   **Face-aware cropping:** two detectors are tried in order:
   - **mediapipe** (primary) — handles sunglasses, hats, non-frontal angles; confidence scores 0–1
   - **OpenCV Haar cascade** (fallback) — `detectMultiScale3` returns unbounded confidence weights; only detections scoring ≥ 5.0 are used (real faces typically score 8+; false positives on objects/mannequins typically score < 5)

   The highest-confidence detection is the *primary face* and is **guaranteed to be fully visible** in the crop. Lower-confidence faces are *secondary* and are included greedily — expanded into the required crop region only if they fit within the target aspect-ratio crop dimensions. The crop window is then positioned to centre the required region within any remaining slack.
6. **Upload** everything back to R2

OAuth refresh tokens are rotated automatically: if Strava issues a new refresh token, the workflow updates the `STRAVA_REFRESH_TOKEN` GitHub secret via a fine-grained PAT.

## Setup

### 1. Strava API application

1. Go to `https://www.strava.com/settings/api` and create an app (any callback URL, e.g. `http://localhost`)
2. Note your **Client ID** and **Client Secret**

### 2. Initial refresh token (one-time)

```bash
# 1. Open in browser — replace YOUR_CLIENT_ID:
https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost&scope=read,activity:read&approval_prompt=force

# 2. After authorising, copy the `code` from the redirect URL, then:
curl -X POST https://www.strava.com/oauth/token \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET \
  -d code=AUTHORIZATION_CODE \
  -d grant_type=authorization_code
# Save the refresh_token from the response
```

### 3. Cloudflare R2

1. Create a bucket named `strava-data`
2. Enable public access and note the public URL
3. Configure CORS to allow your GitHub Pages origin (`https://<user>.github.io`) plus `http://localhost:8080`; include both `GET` and `HEAD` methods
4. Create an R2 API token with read/write access and note the endpoint URL

### 4. GitHub secrets

In **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|---|---|
| `STRAVA_CLIENT_ID` | Strava app Client ID |
| `STRAVA_CLIENT_SECRET` | Strava app Client Secret |
| `STRAVA_REFRESH_TOKEN` | Refresh token from step 2 |
| `R2_ACCESS_KEY_ID` | R2 API token key ID |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret |
| `R2_ENDPOINT` | R2 endpoint URL |
| `GH_PAT` | Fine-grained PAT with **Secrets: read/write** on this repo (enables automatic refresh token rotation) |

To create the PAT: **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**. Set repository access to this repo only, and grant **Secrets: Read and write**.

### 5. GitHub Pages

**Settings → Pages → Source: Deploy from a branch → master / (root)**

### 6. Goals

Edit `goals.json` to whatever your weekly, monthly and yearly goals are, e.g.

```json
{
  "weekly_mi": 20,
  "monthly_mi": 85,
  "yearly_mi": 1000,
  "lifetime_mi": 24901
}
```

`lifetime_mi` is the target for the lifetime card (24,901 mi is the Earth's circumference).

### 7. First run

Trigger the workflow manually: **Actions → Update If New → Run workflow**. After that it runs automatically three times daily.

Your dashboard will be at `https://<username>.github.io/<repo>/`.

## Local Development

The HTML pages detect `localhost` and fetch data from `http://localhost:8080` instead of R2. Serve a local data directory on that port:

```bash
# In a directory containing a data/ folder synced from R2:
python3 -m http.server 8080
```

Then open `index.html` or `routes.html` in a browser (via any other local server, e.g. port 8000).

You do not need the `data/dzi/` directory locally — the routes page falls back to a plain canvas if no Deep Zoom tiles are found.

## Manual Workflows

### Surgical Update

When a specific activity changes (photo replaced, GPS track edited, or activity type corrected), use the **Surgical Update** workflow to recompute only the affected layouts and DZI tiles rather than a full re-render:

**Actions → Surgical Update → Run workflow**

Inputs:
- `activity_ids` — comma-separated Strava activity IDs
- `previous_types` — only if the activity type changed: the type(s) *before* the change, parallel to `activity_ids` (e.g. `"Run,Trail Run"`), so the old type's periods are recomputed too

The workflow automatically determines which periods are affected, re-fetches the activities from Strava, downloads only the necessary data, recomputes layouts, re-renders DZI tiles, and uploads the results. The frozen social and hikes views are never touched.

### Backfill Activities & Photos

If there are gaps in history (e.g. the workflow wasn't running for a period), use the **Backfill Activities & Photos** workflow:

**Actions → Backfill Activities & Photos → Run workflow**

Inputs:
- `since` — fetch all activities on or after this date (`YYYY-MM-DD`)
- `rerender_all` — re-render DZI for every historical period (slow, ~2 hours); leave unchecked to only re-render current week/month/year

### Re-render All DZI

Re-renders DZI tiles for every period (all years, months, week, social, hikes — portrait + landscape) using the current `render_dzi.py`. Use this after changing crop or rendering logic.

**Actions → Re-render All DZI → Run workflow**

No inputs required.

## PWA / Home Screen

The dashboard is installable as a Progressive Web App. On iOS/Android, use "Add to Home Screen" for a full-screen, app-like experience. `manifest.json` declares the app name and icons; `sw.js` provides a network-first service worker so the shell loads offline and updates reliably after deploys.

## App Icon

The Home Screen / PWA icon is drawn from one activity's GPS route: GPS jitter is removed, streets are squared up to the grid, and the route is drawn as a sharp green line on a dark blue map grid. The current icon uses activity `9158465235` (May 28, 2023).

To switch to a different route, keeping the same style:

```bash
pip install Pillow numpy
python3 make_icon.py <activity_id>        # fetches the track from R2 history
python3 make_icon.py --track track.json   # or: [[lat, lng], ...] / a history activity JSON
```

This rewrites `icons/` (`icon.svg`, `icon-180.png` for iOS, `icon-192.png` and `icon-512.png` for the manifest). Commit them, and bump `CACHE_NAME` in `sw.js` so installed copies pick up the change. iOS caches Home Screen icons, so you may need to remove and re-add the app to see a new one. Style and squaring tolerances are constants at the top of `make_icon.py`.

## Key Scripts

| Script | Purpose |
|---|---|
| `fetch-strava.sh` | Fetches week/month/year mileage totals from Strava API |
| `incremental_update.py` | Adds per-activity history JSON and downloads activity photos |
| `compute_layout.py` | Pre-computes boxcraft-packed route layouts for all periods |
| `render_dzi.py` | Smart-crops activity photos to each route's bounding box aspect ratio (face-aware: mediapipe primary + OpenCV fallback), then renders Deep Zoom Image tiles for a given period |
| `render_dzi_all.sh` | Batch-renders DZI for every period (portrait + landscape), including social and hikes |
| `affected_periods.py` | Given a list of activity IDs and a change type, outputs the minimal set of layout and DZI periods that need recomputing |
| `backfill_activities.py` | Fetches missing activities and photos since a given date |
| `extract_photos.py` | One-time: extracts photos from a Strava data export ZIP |
| `make_icon.py` | Generates the PWA / Home Screen icon from an activity's route |
| `fetch_missing_photos.py` | Fetches photos for any history activity that is missing one (use sparingly — hits Strava rate limits) |
| `upload_dzi.py` | Syncs local `data/dzi/` to R2 |
| `process_export.py` | One-time: converts a Strava export ZIP into history JSON |
| `social_classifier.py` | Rules for deciding whether a run was done with friends |
| `classify_social.py` | One-time: stamps `with_friends` on all history JSON using the classifier |
| `review_social.py` | Generates an HTML report for reviewing the classifier's decisions |

The **DZI Upload Speed Test** workflow renders and uploads a single year to measure R2 upload throughput; it is for diagnostics only.
