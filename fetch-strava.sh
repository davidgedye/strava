#!/usr/bin/env bash
set -euo pipefail

# Required environment variables:
#   STRAVA_CLIENT_ID
#   STRAVA_CLIENT_SECRET
#   STRAVA_REFRESH_TOKEN

for var in STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET STRAVA_REFRESH_TOKEN; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: $var is not set" >&2
    exit 1
  fi
done

command -v jq >/dev/null 2>&1 || { echo "Error: jq is required" >&2; exit 1; }

API_BASE="https://www.strava.com/api/v3"

# --- Step 1: Refresh the OAuth access token ---
echo "Refreshing access token..."
TOKEN_RESPONSE=$(curl -sf -X POST "https://www.strava.com/oauth/token" \
  -d "client_id=${STRAVA_CLIENT_ID}" \
  -d "client_secret=${STRAVA_CLIENT_SECRET}" \
  -d "grant_type=refresh_token" \
  -d "refresh_token=${STRAVA_REFRESH_TOKEN}")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token')
NEW_REFRESH_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.refresh_token')

if [[ -z "$ACCESS_TOKEN" || "$ACCESS_TOKEN" == "null" ]]; then
  echo "Error: Failed to obtain access token" >&2
  echo "Response: $TOKEN_RESPONSE" >&2
  exit 1
fi

# If the refresh token rotated, export it so the workflow can update the secret
if [[ "$NEW_REFRESH_TOKEN" != "$STRAVA_REFRESH_TOKEN" && "$NEW_REFRESH_TOKEN" != "null" ]]; then
  echo "Refresh token rotated."
  echo "NEW_REFRESH_TOKEN=${NEW_REFRESH_TOKEN}" >> "${GITHUB_OUTPUT:-/dev/null}"
fi

AUTH_HEADER="Authorization: Bearer ${ACCESS_TOKEN}"

# --- Step 2: Fetch athlete stats for YTD run totals ---
echo "Fetching athlete info..."
ATHLETE=$(curl -sf -H "$AUTH_HEADER" "${API_BASE}/athlete")
ATHLETE_ID=$(echo "$ATHLETE" | jq -r '.id')

if [[ -z "$ATHLETE_ID" || "$ATHLETE_ID" == "null" ]]; then
  echo "Error: Failed to fetch athlete ID" >&2
  exit 1
fi

echo "Fetching athlete stats for ID ${ATHLETE_ID}..."
STATS=$(curl -sf -H "$AUTH_HEADER" "${API_BASE}/athletes/${ATHLETE_ID}/stats")

# YTD distance in meters → miles (1 mile = 1609.344 m)
YTD_DISTANCE_M=$(echo "$STATS" | jq '.ytd_run_totals.distance')
YTD_DISTANCE_MI=$(echo "$YTD_DISTANCE_M" | awk '{printf "%.1f", $1 / 1609.344}')

# All-time lifetime distance
LIFETIME_DISTANCE_M=$(echo "$STATS" | jq '.all_run_totals.distance')
LIFETIME_DISTANCE_MI=$(echo "$LIFETIME_DISTANCE_M" | awk '{printf "%.1f", $1 / 1609.344}')

# --- Step 3: Fetch activities for the current week (Monday–Sunday) and month ---
CURRENT_YEAR=$(date -u +%Y)
CURRENT_MONTH=$(date -u +%m)

# Find start of current week (Monday 00:00 UTC)
DOW=$(date -u +%u)  # 1=Monday, 7=Sunday
DAYS_SINCE_MONDAY=$(( DOW - 1 ))
if date -d "now" +%s >/dev/null 2>&1; then
  # GNU date
  WEEK_START_UNIX=$(date -u -d "$DAYS_SINCE_MONDAY days ago 00:00:00" +%s)
  MONTH_START_UNIX=$(date -u -d "${CURRENT_YEAR}-${CURRENT_MONTH}-01" +%s)
else
  # BSD date
  WEEK_START_UNIX=$(date -u -v-"${DAYS_SINCE_MONDAY}"d -v0H -v0M -v0S +%s)
  MONTH_START_UNIX=$(date -u -jf "%Y-%m-%d" "${CURRENT_YEAR}-${CURRENT_MONTH}-01" +%s 2>/dev/null || date -u +%s)
fi

# Use the earlier of week start and month start so one API call covers both
if [[ "$WEEK_START_UNIX" -lt "$MONTH_START_UNIX" ]]; then
  FETCH_AFTER=$WEEK_START_UNIX
else
  FETCH_AFTER=$MONTH_START_UNIX
fi

echo "Fetching activities since $(date -u -d @"$FETCH_AFTER" 2>/dev/null || echo "$FETCH_AFTER")..."
ACTIVITIES=$(curl -sf -H "$AUTH_HEADER" \
  "${API_BASE}/athlete/activities?after=${FETCH_AFTER}&per_page=200")

# Filter for all run activities (matches Strava's "All Runs" category).
# Checks both the deprecated `type` and the current `sport_type` field, since
# manually entered activities may only have sport_type set.
WEEK_DISTANCE_MI=$(echo "$ACTIVITIES" | jq --argjson after "$WEEK_START_UNIX" \
  '[.[] | select(.type == "Run" or .sport_type == "Run" or .sport_type == "TrailRun" or .sport_type == "Treadmill" or .sport_type == "VirtualRun") | select((.start_date | fromdateiso8601) >= $after) | .distance] | add // 0 | . / 1609.344 | . * 10 | round / 10')

MONTH_DISTANCE_MI=$(echo "$ACTIVITIES" | jq --argjson after "$MONTH_START_UNIX" \
  '[.[] | select(.type == "Run" or .sport_type == "Run" or .sport_type == "TrailRun" or .sport_type == "Treadmill" or .sport_type == "VirtualRun") | select((.start_date | fromdateiso8601) >= $after) | .distance] | add // 0 | . / 1609.344 | . * 10 | round / 10')

# --- Step 4: Write output ---
UPDATED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
CURRENT_MONTH_STR="${CURRENT_YEAR}-${CURRENT_MONTH}"

mkdir -p data

jq -n \
  --arg updated_at "$UPDATED_AT" \
  --argjson ytd_distance_mi "$YTD_DISTANCE_MI" \
  --argjson week_distance_mi "$WEEK_DISTANCE_MI" \
  --argjson month_distance_mi "$MONTH_DISTANCE_MI" \
  --argjson lifetime_distance_mi "$LIFETIME_DISTANCE_MI" \
  --arg current_month "$CURRENT_MONTH_STR" \
  --argjson current_year "$CURRENT_YEAR" \
  '{
    updated_at: $updated_at,
    ytd_distance_mi: $ytd_distance_mi,
    week_distance_mi: $week_distance_mi,
    month_distance_mi: $month_distance_mi,
    lifetime_distance_mi: $lifetime_distance_mi,
    current_month: $current_month,
    current_year: ($current_year | tonumber)
  }' > data/strava.json

echo "Wrote data/strava.json:"
cat data/strava.json
