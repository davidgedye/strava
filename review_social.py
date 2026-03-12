#!/usr/bin/env python3
"""
Generate an HTML review report of the "with friends" classifier.
Opens all runs from activities.csv in the Strava export zip.

Usage:
    python3 review_social.py stravaExport_3_7_2026.zip > /tmp/social_review.html
"""
import csv, io, re, sys, zipfile, html
from social_classifier import classify_with_reasons as classify

ZIP_PATH = sys.argv[1] if len(sys.argv) > 1 else 'stravaExport_3_7_2026.zip'

def is_run(row):
    return 'Run' in row.get('Activity Type', '')

# ── Load ──────────────────────────────────────────────────────────────────────

z = zipfile.ZipFile(ZIP_PATH)
with z.open('activities.csv') as f:
    rows = list(csv.DictReader(io.TextIOWrapper(f)))

runs = [r for r in rows if is_run(r)]

social, not_social, bean_excluded = [], [], []
for r in runs:
    name = r.get('Activity Name', '')
    desc = r.get('Activity Description', '')
    is_social, reasons = classify(name, desc)
    r['_reasons'] = reasons
    if 'excluded: Bean' in reasons:
        bean_excluded.append(r)
    elif is_social:
        social.append(r)
    else:
        not_social.append(r)

# ── HTML output ───────────────────────────────────────────────────────────────

def esc(s): return html.escape(str(s or ''))

def reason_badges(reasons):
    out = []
    for r in reasons:
        color = '#2d6a4f' if 'Expect' in r else '#1d3a6e'
        out.append(f'<span style="background:{color};color:#fff;padding:2px 7px;border-radius:10px;font-size:11px;white-space:nowrap">{esc(r)}</span>')
    return ' '.join(out)

def row_html(r, idx, section):
    name    = esc(r.get('Activity Name', ''))
    desc    = esc(r.get('Activity Description', ''))
    from datetime import datetime
    raw_date = r.get('Activity Date', '')
    try:    date = datetime.strptime(raw_date, '%b %d, %Y, %I:%M:%S %p').strftime('%Y-%m-%d')
    except: date = raw_date[:16]
    date = esc(date)
    dist    = r.get('Distance', '')
    reasons = r.get('_reasons', [])
    act_id  = esc(r.get('Activity ID', ''))
    bg = '#1a1a2e' if idx % 2 == 0 else '#16213e'
    strava_link = f'https://www.strava.com/activities/{act_id}' if act_id else ''
    name_html = f'<a href="{strava_link}" target="_blank" style="color:#93c5fd;text-decoration:none" onclick="event.stopPropagation()">{name}</a>' if strava_link else name
    badges = reason_badges(reasons) if reasons else ''
    desc_html = f'<div style="color:#888;font-size:12px;margin-top:3px">{desc}</div>' if desc else ''
    dist_html = f'<span style="color:#6b7280;font-size:12px">{esc(dist)} m</span>'
    raw_name = r.get('Activity Name', '').replace('"', '&quot;')
    return f'''<tr class="flaggable" data-id="{act_id}" data-name="{raw_name}" data-section="{section}" onclick="toggleFlag(this)" style="background:{bg}">
  <td style="padding:8px 20px 8px 12px;color:#6b7280;font-size:12px;white-space:nowrap;min-width:110px">{date}</td>
  <td style="padding:8px 12px">{name_html}{desc_html}</td>
  <td style="padding:8px 6px">{dist_html}</td>
  <td style="padding:8px 12px">{badges}</td>
</tr>'''

print(f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Social Run Classifier Review</title>
<style>
  body {{ background:#0f0f1a; color:#e2e8f0; font:14px/1.5 -apple-system,sans-serif; margin:0; padding:20px; }}
  h1 {{ color:#f1f5f9; margin-bottom:4px }}
  h2 {{ color:#94a3b8; font-size:16px; margin:32px 0 8px }}
  .summary {{ background:#1e293b; border-radius:8px; padding:14px 20px; margin-bottom:24px; display:flex; gap:32px }}
  .stat {{ text-align:center }}
  .stat-n {{ font-size:32px; font-weight:700; color:#f1f5f9 }}
  .stat-l {{ font-size:12px; color:#94a3b8 }}
  table {{ width:100%; border-collapse:collapse }}
  th {{ text-align:left; padding:8px 12px; background:#1e293b; color:#94a3b8; font-size:12px; text-transform:uppercase; letter-spacing:.05em; position:sticky; top:0 }}
  .section {{ border:1px solid #334155; border-radius:8px; overflow:hidden; margin-bottom:32px }}
  .rule {{ background:#1e293b; border-radius:8px; padding:14px 20px; font-family:monospace; font-size:13px; color:#a5f3fc; margin-bottom:24px; white-space:pre }}
  tr.flaggable {{ cursor:pointer; transition:background .1s }}
  tr.flaggable:hover td {{ filter:brightness(1.3) }}
  tr.flagged td {{ background:#4a1942 !important; }}
  tr.flagged td:first-child::before {{ content:'⚑ '; color:#f472b6 }}
  #flag-bar {{
    position:fixed; bottom:20px; right:20px; background:#1e293b; border:1px solid #475569;
    border-radius:12px; padding:14px 18px; z-index:100; min-width:220px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  }}
  #flag-bar h3 {{ margin:0 0 10px; font-size:13px; color:#94a3b8 }}
  .flag-count {{ font-size:22px; font-weight:700; color:#f1f5f9 }}
  .flag-sub {{ font-size:11px; color:#64748b; margin-bottom:10px }}
  #copy-btn {{
    width:100%; padding:8px; background:#6d28d9; color:#fff; border:none;
    border-radius:7px; cursor:pointer; font-size:13px; font-weight:600;
  }}
  #copy-btn:hover {{ background:#7c3aed }}
  #copy-btn:active {{ background:#5b21b6 }}
  #copied-msg {{ font-size:11px; color:#4ade80; margin-top:6px; text-align:center; display:none }}
</style>
<script>
window.flagged = {{}};  // id → {{name, section}}
function toggleFlag(tr) {{
  const id = tr.dataset.id;
  if (flagged[id]) {{ delete flagged[id]; tr.classList.remove('flagged'); }}
  else {{ flagged[id] = {{name: tr.dataset.name, section: tr.dataset.section}}; tr.classList.add('flagged'); }}
  updateBar();
}}
function updateBar() {{
  const ids = Object.keys(flagged);
  const fp = ids.filter(id => flagged[id].section === 'social').length;
  const fn = ids.filter(id => flagged[id].section === 'not').length;
  const bean = ids.filter(id => flagged[id].section === 'bean').length;
  document.getElementById('flag-total').textContent = ids.length;
  document.getElementById('flag-detail').textContent =
    `${{fp}} false positive · ${{fn}} false negative · ${{bean}} bean`;
}}
function copyFlags() {{
  const fp = [], fn = [], bean = [];
  for (const [id, info] of Object.entries(flagged)) {{
    const obj = {{id, name: info.name}};
    if (info.section === 'social') fp.push(obj);
    else if (info.section === 'not') fn.push(obj);
    else bean.push(obj);
  }}
  const out = JSON.stringify({{false_positives: fp, false_negatives: fn, bean_issues: bean}}, null, 2);
  navigator.clipboard.writeText(out).then(() => {{
    const m = document.getElementById('copied-msg');
    m.style.display = 'block';
    setTimeout(() => m.style.display = 'none', 2000);
  }});
}}
</script>
</head>
<body>
<div id="flag-bar">
  <h3>Flagged corrections</h3>
  <div class="flag-count"><span id="flag-total">0</span></div>
  <div class="flag-sub" id="flag-detail">0 false positive · 0 false negative · 0 bean</div>
  <button id="copy-btn" onclick="copyFlags()">Copy JSON to clipboard</button>
  <div id="copied-msg">Copied!</div>
</div>
<h1>Social Run Classifier — Review Report</h1>
<p style="color:#94a3b8">Click any row to flag it as a mistake. Then hit "Copy JSON" and paste to Claude.</p>

<div class="summary">
  <div class="stat"><div class="stat-n">{len(runs)}</div><div class="stat-l">Total runs</div></div>
  <div class="stat"><div class="stat-n" style="color:#4ade80">{len(social)}</div><div class="stat-l">With Friends ✓</div></div>
  <div class="stat"><div class="stat-n" style="color:#f87171">{len(not_social)}</div><div class="stat-l">Not Social</div></div>
  <div class="stat"><div class="stat-n" style="color:#fbbf24">{len(bean_excluded)}</div><div class="stat-l">Bean excluded</div></div>
  <div class="stat"><div class="stat-n" style="color:#a78bfa">{len(social)/len(runs)*100:.1f}%</div><div class="stat-l">Social rate</div></div>
</div>

<div class="rule">Classifier rules (applied to name + description):
  1. EXCLUDE if \\bbean\\b  (case-insensitive)
  2. INCLUDE if "expect delays"  (case-insensitive)
  3. INCLUDE if \\bwith\\s+[A-Z]  (capital letter follows "with")</div>

<h2>✓ Classified as WITH FRIENDS ({len(social)} runs) — check for false positives</h2>
<div class="section">
<table>
<thead><tr><th>Date</th><th>Name / Description</th><th>Distance</th><th>Match reason</th></tr></thead>
<tbody>
{"".join(row_html(r, i, 'social') for i, r in enumerate(social))}
</tbody>
</table>
</div>

<h2>🐾 Bean-excluded ({len(bean_excluded)} runs)</h2>
<div class="section">
<table>
<thead><tr><th>Date</th><th>Name / Description</th><th>Distance</th><th>Notes</th></tr></thead>
<tbody>
{"".join(row_html(r, i, 'bean') for i, r in enumerate(bean_excluded))}
</tbody>
</table>
</div>

<h2>✗ NOT classified as social ({len(not_social)} runs) — scan for false negatives</h2>
<p style="color:#94a3b8;font-size:13px">All {len(not_social)} non-social runs shown. Look for runs that were actually with friends but weren't caught.</p>
<div class="section">
<table>
<thead><tr><th>Date</th><th>Name / Description</th><th>Distance</th><th></th></tr></thead>
<tbody>
{"".join(row_html(r, i, 'not') for i, r in enumerate(not_social))}
</tbody>
</table>
</div>

</body>
</html>
''')
