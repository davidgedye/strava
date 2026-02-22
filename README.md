# Strava Running Goals Dashboard

A static dashboard that tracks progress against yearly and monthly running distance goals using data from the Strava API. Hosted on GitHub Pages with no backend — a daily GitHub Action fetches your data and commits it as static JSON.

## Setup

### 1. Create a Strava API Application

1. Go to https://www.strava.com/settings/api
2. Create an application (use any website/callback URL, e.g., `http://localhost`)
3. Note your **Client ID** and **Client Secret**

### 2. Get Your Initial Refresh Token

Authorize your app to access your data (one-time manual step):

1. Open this URL in your browser (replace `YOUR_CLIENT_ID`):

   ```
   https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost&scope=read,activity:read&approval_prompt=force
   ```

2. Authorize the app. You'll be redirected to `http://localhost?code=AUTHORIZATION_CODE&...`
3. Copy the `code` parameter from the URL
4. Exchange it for tokens:

   ```bash
   curl -X POST https://www.strava.com/oauth/token \
     -d client_id=YOUR_CLIENT_ID \
     -d client_secret=YOUR_CLIENT_SECRET \
     -d code=AUTHORIZATION_CODE \
     -d grant_type=authorization_code
   ```

5. Save the `refresh_token` from the response

### 3. Configure GitHub Repository Secrets

In your repo, go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `STRAVA_CLIENT_ID` | Your Strava app Client ID |
| `STRAVA_CLIENT_SECRET` | Your Strava app Client Secret |
| `STRAVA_REFRESH_TOKEN` | The refresh token from step 2 |

**Recommended**: Add a `GH_PAT` secret to enable automatic refresh token rotation. Without this, if Strava rotates your refresh token, the workflow will break and require manual re-authorization.

To create the token:
1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Set **Repository access** to "Only select repositories" and pick this repo
3. Under **Repository permissions**, set **Secrets** to **Read and write**
4. Set expiration to "No expiration" for a fully hands-off setup
5. Add the token as a `GH_PAT` repository secret

### 4. Enable GitHub Pages

Go to **Settings → Pages** and set:
- Source: **Deploy from a branch**
- Branch: **main**, folder: **/ (root)**

### 5. Set Your Goals

Edit `goals.json` to set your targets:

```json
{
  "weekly_mi": 20,
  "monthly_mi": 80,
  "yearly_mi": 1000
}
```

### 6. Run

- Trigger the action manually: **Actions → Fetch Strava Data → Run workflow**
- After that it runs automatically twice daily (6am and 6pm Pacific)
- Your dashboard will be available at `https://<username>.github.io/<repo>/`

## Local Testing

```bash
export STRAVA_CLIENT_ID=your_id
export STRAVA_CLIENT_SECRET=your_secret
export STRAVA_REFRESH_TOKEN=your_token
bash fetch-strava.sh
```

Then open `index.html` in a browser (e.g., `python3 -m http.server` and visit `http://localhost:8000`).

## Files

| File | Purpose |
|---|---|
| `index.html` | Dashboard (static HTML/CSS/JS) |
| `goals.json` | Your distance targets |
| `data/strava.json` | Fetched Strava data (auto-generated) |
| `fetch-strava.sh` | Script that calls the Strava API |
| `.github/workflows/fetch-strava.yml` | Daily cron job |
