# Strava Running Dashboard

A personal running dashboard with three views, hosted on GitHub Pages. A daily GitHub Action pulls data from the Strava API, processes it, and uploads everything to Cloudflare R2. The HTML/JS is served from GitHub Pages; all data is fetched from R2 at runtime. There is no backend.

## Pages

| Page | URL | Description |
|---|---|---|
| **Progress** | `index.html` | Weekly / monthly / yearly distance vs. goals, with fireworks on completion |
| **Routes** | `routes.html` | Full-screen canvas of GPS route outlines, packed glacier-style, with a Deep Zoom photo background |
| **Lifetime** | `planet.html` | Cumulative lifetime distance visualisation |

`routes.html` accepts a `?period=` query parameter:
- `week` — current rolling week
- `YYYY-MM` — a specific month
- `YYYY` — a full year
- `social` — runs inferred to have been done with other people

The routes page auto-detects portrait vs landscape and loads the appropriate layout.

## Architecture

```
GitHub Actions (daily)
  └─ fetch-strava.sh        ← Strava API → summary JSON (week/month/year totals)
  └─ incremental_update.py  ← Strava API → per-activity history JSON + photos
  └─ compute_layout.py      ← history/ + layouts/ → glacier-packed route layouts
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

The `fetch-strava.yml` workflow runs at ~1 pm Pacific and does the following:

1. **Download** `history/`, `layouts/`, and `photos/` from R2
2. **Fetch** current week/month/year summaries via `fetch-strava.sh`
3. **Update history** — `incremental_update.py` adds JSON for any new activities and downloads their photos
4. **Compute layouts** — `compute_layout.py` regenerates layouts for the current week/month/year (historical periods are cached)
5. **Render DZI** — `render_dzi.py` smart-crops each activity photo to the aspect ratio of its route's bounding box (prioritising faces where detected), then renders Deep Zoom tiles for the current week/month/year; the social DZI is only re-rendered if the friend count changed
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

Edit `goals.json`:

```json
{
  "weekly_mi": 20,
  "monthly_mi": 80,
  "yearly_mi": 1000
}
```

### 7. First run

Trigger the workflow manually: **Actions → Fetch Strava Data → Run workflow**. After that it runs automatically once daily.

Your dashboard will be at `https://<username>.github.io/<repo>/`.

## Local Development

The HTML pages detect `localhost` and fetch data from `http://localhost:8080` instead of R2. Serve a local data directory on that port:

```bash
# In a directory containing a data/ folder synced from R2:
python3 -m http.server 8080
```

Then open `index.html` or `routes.html` in a browser (via any other local server, e.g. port 8000).

You do not need the `data/dzi/` directory locally — the routes page falls back to a plain canvas if no Deep Zoom tiles are found.

## Backfill

If there are gaps in history (e.g. the workflow wasn't running for a period), use the **Backfill Activities & Photos** workflow:

**Actions → Backfill Activities & Photos → Run workflow**

Inputs:
- `since` — fetch all activities on or after this date (`YYYY-MM-DD`)
- `rerender_all` — re-render DZI for every historical period (slow, ~2 hours); leave unchecked to only re-render current week/month/year

## Key Scripts

| Script | Purpose |
|---|---|
| `fetch-strava.sh` | Fetches week/month/year mileage totals from Strava API |
| `incremental_update.py` | Adds per-activity history JSON and downloads activity photos |
| `compute_layout.py` | Pre-computes glacier-packed route layouts for all periods |
| `render_dzi.py` | Smart-crops activity photos to each route's bounding box aspect ratio (faces prioritised), then renders Deep Zoom Image tiles for a given period |
| `render_dzi_all.sh` | Batch-renders DZI for every period (portrait + landscape) |
| `backfill_activities.py` | Fetches missing activities and photos since a given date |
| `extract_photos.py` | One-time: extracts photos from a Strava data export ZIP |
