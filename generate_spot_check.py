#!/usr/bin/env python3
"""
Generate spot check data and HTML file from the latest booking_classification.csv.
Samples 10 random merchants per category and produces:
  - output/_spot_check_data.json
  - output/spot_check.html
"""

import csv
import json
import html
import random
import os
from collections import defaultdict
from pathlib import Path

random.seed(42)

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "output" / "booking_classification.csv"
JSON_PATH = BASE_DIR / "output" / "_spot_check_data.json"
HTML_PATH = BASE_DIR / "output" / "spot_check.html"

# ── category definitions ──────────────────────────────────────────────────────
CATEGORIES = [
    {
        "key": "3p_booking_is_website",
        "title": "3P Booking IS Website",
        "bookable": True,
        "color": "#4fc3f7",
        "desc": "The merchant's website URL is hosted directly on a booking platform (e.g. vagaro.com/merchant, squareup.com/merchant)",
        "verify": "Confirm the URL is a booking platform domain, not just the merchant's own site",
    },
    {
        "key": "3p_booking_embedded",
        "title": "3P Booking Embedded",
        "bookable": True,
        "color": "#81c784",
        "desc": "A third-party booking widget is embedded on the merchant's own website via script/iframe",
        "verify": "Look for a booking button/widget on the page that opens an inline booking flow",
    },
    {
        "key": "3p_booking_external",
        "title": "3P Booking External",
        "bookable": True,
        "color": "#aed581",
        "desc": "The merchant's site links out to an external booking platform page",
        "verify": "Find a 'Book Now' link that navigates to a different domain (booking platform)",
    },
    {
        "key": "internal_booking",
        "title": "Internal Booking",
        "bookable": True,
        "color": "#fff176",
        "desc": "The merchant has built their own custom booking system on their website",
        "verify": "Look for a booking/scheduling form that stays on the merchant's domain",
    },
    {
        "key": "call_email_only",
        "title": "Call/Email Only",
        "bookable": False,
        "color": "#ffb74d",
        "desc": "No online booking — only phone numbers or email addresses for appointment scheduling",
        "verify": "Confirm there's no booking button/widget, only phone/email contact info",
    },
    {
        "key": "no_booking_found",
        "title": "No Booking Found",
        "bookable": False,
        "color": "#e57373",
        "desc": "Website exists and loads, but no booking mechanism was detected",
        "verify": "Browse the site — is there really no way to book online?",
    },
]

SAMPLES_PER_CAT = 10


def read_csv():
    """Read CSV and group rows by category."""
    by_cat = defaultdict(list)
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cat = row.get("category", "").strip()
            if cat:
                by_cat[cat].append(row)
    return by_cat


def sample_data(by_cat):
    """Sample up to SAMPLES_PER_CAT from each target category."""
    sampled = {}
    for cat_def in CATEGORIES:
        key = cat_def["key"]
        pool = by_cat.get(key, [])
        n = min(SAMPLES_PER_CAT, len(pool))
        sampled[key] = random.sample(pool, n) if n > 0 else []
    return sampled


def count_categories(by_cat):
    """Count total per category for all rows."""
    counts = {}
    total = 0
    for cat_def in CATEGORIES:
        c = len(by_cat.get(cat_def["key"], []))
        counts[cat_def["key"]] = c
        total += c
    # also count categories we're not spotchecking
    for k, v in by_cat.items():
        if k not in counts:
            counts[k] = len(v)
            total += len(v)
    return counts, total


def esc(text):
    """HTML-escape a string."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def make_url_cell(url):
    """Create a URL table cell, or dash if empty."""
    if not url or url.strip() == "":
        return '<span class="na">\u2014</span>'
    display = url if len(url) <= 55 else url[:52] + "..."
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(display)}</a>'


def make_screenshot_cell(screenshot_path, website_url):
    """Create screenshot link cell."""
    if not screenshot_path or screenshot_path.strip() == "":
        return ""
    # Make path relative to output dir
    fname = os.path.basename(screenshot_path)
    return f'<a href="screenshots/{esc(fname)}" target="_blank">view</a>'


def generate_html(sampled, counts, total_merchants):
    """Generate the complete spot_check.html."""

    # Count total samples
    total_samples = sum(len(v) for v in sampled.values())

    # Compute bookable total from counts
    bookable_keys = {c["key"] for c in CATEGORIES if c["bookable"]}
    total_bookable = sum(counts.get(k, 0) for k in bookable_keys)
    bookable_pct = round(total_bookable / total_merchants * 100, 1) if total_merchants else 0

    lines = []
    lines.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Booking Classification — Accuracy Spot Check (v3)</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#1a1a2e; color:#e0e0e0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; padding:24px; }
  h1 { font-size:1.8rem; margin-bottom:8px; color:#fff; }
  .subtitle { color:#aaa; margin-bottom:24px; font-size:0.95rem; }
  .summary-bar { display:flex; gap:16px; margin-bottom:32px; flex-wrap:wrap; }
  .summary-card { background:#16213e; border-radius:10px; padding:16px 24px; min-width:140px; text-align:center; }
  .summary-card .num { font-size:2rem; font-weight:700; color:#fff; }
  .summary-card .lbl { font-size:0.8rem; color:#aaa; margin-top:4px; }
  #card-pass .num { color:#66bb6a; }
  #card-fail .num { color:#ef5350; }
  #card-unclear .num { color:#ffa726; }
  #card-pending .num { color:#78909c; }
  #card-accuracy .num { color:#4fc3f7; }
  .pipeline-stats { background:#16213e; border-radius:10px; padding:16px 20px; margin-bottom:32px; }
  .pipeline-stats h2 { font-size:1.1rem; color:#fff; margin-bottom:10px; }
  .stat-row { display:flex; flex-wrap:wrap; gap:12px; }
  .stat-item { font-size:0.85rem; color:#bbb; padding:4px 12px; background:#0f3460; border-radius:6px; }
  .stat-item strong { color:#fff; }
  .category-section { margin-bottom:32px; }
  .cat-header { background:#16213e; border-radius:10px; padding:16px 20px; margin-bottom:12px; }
  .cat-header h2 { font-size:1.2rem; color:#fff; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .count { font-size:0.85rem; color:#888; font-weight:400; }
  .cat-desc { color:#bbb; font-size:0.9rem; margin-top:6px; }
  .cat-verify { color:#90caf9; font-size:0.85rem; margin-top:4px; }
  .cat-score { margin-top:8px; font-size:0.85rem; }
  .badge { font-size:0.7rem; padding:3px 8px; border-radius:4px; font-weight:600; text-transform:uppercase; }
  .badge.bookable { background:#2e7d3240; color:#66bb6a; }
  .badge.not-bookable { background:#c6282840; color:#ef5350; }
  table { width:100%; border-collapse:collapse; background:#16213e; border-radius:10px; overflow:hidden; font-size:0.85rem; }
  thead { background:#0f3460; }
  th { padding:10px 12px; text-align:left; font-weight:600; color:#90caf9; font-size:0.8rem; text-transform:uppercase; }
  td { padding:8px 12px; border-top:1px solid #1a1a3e; }
  tr:hover { background:#1a2540; }
  .idx { color:#666; width:30px; }
  .name { font-weight:500; color:#fff; max-width:200px; }
  .url { max-width:250px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .evidence { max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#aaa; font-size:0.8rem; }
  .na { color:#555; }
  a { color:#4fc3f7; text-decoration:none; }
  a:hover { text-decoration:underline; }
  .verdict { white-space:nowrap; }
  .btn-pass, .btn-fail, .btn-unclear { border:none; border-radius:6px; padding:5px 10px; cursor:pointer; font-size:0.9rem; margin-right:4px; opacity:0.5; transition:all 0.15s; }
  .btn-pass { background:#2e7d3240; color:#66bb6a; }
  .btn-fail { background:#c6282840; color:#ef5350; }
  .btn-unclear { background:#e6510040; color:#ffa726; }
  .btn-pass:hover, .btn-fail:hover, .btn-unclear:hover { opacity:1; }
  .btn-pass.active { opacity:1; background:#2e7d32; color:#fff; }
  .btn-fail.active { opacity:1; background:#c62828; color:#fff; }
  .btn-unclear.active { opacity:1; background:#e65100; color:#fff; }
  tr.row-pass { background:#1b3a1b20; }
  tr.row-fail { background:#3a1b1b20; }
  tr.row-unclear { background:#3a2e1b20; }
</style>
</head>
<body>""")

    lines.append(f'<h1>Accuracy Spot Check <span style="font-size:0.7em;color:#4fc3f7">v3 — latest pipeline</span></h1>')
    lines.append(f'<p class="subtitle">10 random merchants per category — click website links to verify classification. Mark each as pass/fail/unclear.</p>')

    # Summary bar
    lines.append(f'''<div class="summary-bar">
  <div class="summary-card" id="card-total"><div class="num" id="num-total">{total_samples}</div><div class="lbl">Total Samples</div></div>
  <div class="summary-card" id="card-pass"><div class="num" id="num-pass">0</div><div class="lbl">Pass</div></div>
  <div class="summary-card" id="card-fail"><div class="num" id="num-fail">0</div><div class="lbl">Fail</div></div>
  <div class="summary-card" id="card-unclear"><div class="num" id="num-unclear">0</div><div class="lbl">Unclear</div></div>
  <div class="summary-card" id="card-pending"><div class="num" id="num-pending">{total_samples}</div><div class="lbl">Pending</div></div>
  <div class="summary-card" id="card-accuracy"><div class="num" id="num-accuracy">&mdash;</div><div class="lbl">Accuracy</div></div>
</div>''')

    # Pipeline stats bar
    lines.append(f'''<div class="pipeline-stats">
  <h2>Pipeline Summary</h2>
  <div class="stat-row">
    <div class="stat-item"><strong>{total_merchants:,}</strong> Total Merchants</div>
    <div class="stat-item"><strong>{total_bookable:,}</strong> Bookable ({bookable_pct}%)</div>''')
    for cat_def in CATEGORIES:
        k = cat_def["key"]
        c = counts.get(k, 0)
        lines.append(f'    <div class="stat-item"><strong>{c:,}</strong> {cat_def["title"]}</div>')
    lines.append('  </div>\n</div>')

    # Category sections
    for cat_def in CATEGORIES:
        key = cat_def["key"]
        rows = sampled.get(key, [])
        badge_cls = "bookable" if cat_def["bookable"] else "not-bookable"
        badge_txt = "BOOKABLE" if cat_def["bookable"] else "NOT BOOKABLE"
        n_samples = len(rows)

        lines.append(f'''
    <div class="category-section" id="cat-{key}">
      <div class="cat-header" style="border-left: 4px solid {cat_def['color']}">
        <h2>{esc(cat_def['title'])} <span class="badge {badge_cls}">{badge_txt}</span> <span class="count">({n_samples} samples &mdash; {counts.get(key, 0):,} total in pipeline)</span></h2>
        <p class="cat-desc">{esc(cat_def['desc'])}</p>
        <p class="cat-verify"><strong>How to verify:</strong> {esc(cat_def['verify'])}</p>
        <div class="cat-score" id="score-{key}"></div>
      </div>
      <table>
        <thead><tr><th>#</th><th>Merchant</th><th>Website</th><th>Platform</th><th>Evidence</th><th>Booking URL</th><th>Screenshot</th><th>Verdict</th></tr></thead>
        <tbody>''')

        for i, row in enumerate(rows):
            row_id = f"{key}_{i}"
            merchant = row.get("merchant_name", "") or ""
            website = row.get("website_url", "") or ""
            platform = row.get("platform", "") or ""
            evidence = row.get("evidence", "") or ""
            booking_url = row.get("booking_url", "") or ""
            screenshot = row.get("screenshot", "") or ""

            lines.append(f'''<tr id="row-{row_id}" data-cat="{key}">
          <td class="idx">{i + 1}</td>
          <td class="name">{esc(merchant)}</td>
          <td class="url">{make_url_cell(website)}</td>
          <td>{esc(platform)}</td>
          <td class="evidence">{esc(evidence)}</td>
          <td class="url">{make_url_cell(booking_url)}</td>
          <td>{make_screenshot_cell(screenshot, website)}</td>
          <td class="verdict">
            <button class="btn-pass" onclick="mark('{row_id}','pass')">&#10003;</button>
            <button class="btn-fail" onclick="mark('{row_id}','fail')">&#10007;</button>
            <button class="btn-unclear" onclick="mark('{row_id}','unclear')">?</button>
          </td>
        </tr>''')

        lines.append('</tbody>\n      </table>\n    </div>')

    # JavaScript
    lines.append("""
<script>
const verdicts = {};
function mark(rowId, verdict) {
  const row = document.getElementById('row-' + rowId);
  const cat = row.dataset.cat;
  if (verdicts[rowId] === verdict) {
    delete verdicts[rowId];
    row.className = '';
    row.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  } else {
    verdicts[rowId] = verdict;
    row.className = 'row-' + verdict;
    row.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    row.querySelector('.btn-' + verdict).classList.add('active');
  }
  updateSummary();
  updateCatScore(cat);
}
function updateSummary() {
  const vals = Object.values(verdicts);
  const pass = vals.filter(v => v === 'pass').length;
  const fail = vals.filter(v => v === 'fail').length;
  const unclear = vals.filter(v => v === 'unclear').length;
  const total = document.querySelectorAll('tr[data-cat]').length;
  const pending = total - pass - fail - unclear;
  document.getElementById('num-pass').textContent = pass;
  document.getElementById('num-fail').textContent = fail;
  document.getElementById('num-unclear').textContent = unclear;
  document.getElementById('num-pending').textContent = pending;
  const judged = pass + fail;
  document.getElementById('num-accuracy').textContent = judged > 0 ? Math.round(pass / judged * 100) + '%' : '\u2014';
}
function updateCatScore(cat) {
  const rows = document.querySelectorAll('tr[data-cat="' + cat + '"]');
  let pass=0, fail=0, unclear=0, pending=0;
  rows.forEach(r => {
    const id = r.id.replace('row-','');
    if (verdicts[id] === 'pass') pass++;
    else if (verdicts[id] === 'fail') fail++;
    else if (verdicts[id] === 'unclear') unclear++;
    else pending++;
  });
  const el = document.getElementById('score-' + cat);
  if (pass + fail + unclear === 0) { el.innerHTML = ''; }
  else {
    const acc = (pass + fail) > 0 ? Math.round(pass/(pass+fail)*100) : '\u2014';
    el.innerHTML = '<span style="color:#66bb6a">' + pass + ' pass</span> \\u00B7 <span style="color:#ef5350">' + fail + ' fail</span> \\u00B7 <span style="color:#ffa726">' + unclear + ' unclear</span> \\u00B7 <span style="color:#78909c">' + pending + ' pending</span> \\u00B7 <strong style="color:#4fc3f7">Accuracy: ' + acc + '%</strong>';
  }
}
</script>
</body>
</html>""")

    return "\n".join(lines)


def main():
    print("Reading CSV...")
    by_cat = read_csv()

    # Print category counts
    total_all = 0
    for k, v in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        print(f"  {k}: {len(v)}")
        total_all += len(v)
    print(f"  TOTAL: {total_all}")

    print("\nSampling 10 per category...")
    sampled = sample_data(by_cat)
    for cat_def in CATEGORIES:
        key = cat_def["key"]
        print(f"  {key}: {len(sampled.get(key, []))} samples")

    counts, _ = count_categories(by_cat)

    # Use the known total from the pipeline
    total_merchants = total_all

    # Write JSON
    json_data = {}
    for cat_def in CATEGORIES:
        key = cat_def["key"]
        json_data[key] = []
        for row in sampled.get(key, []):
            json_data[key].append({
                "merchant_name": row.get("merchant_name", ""),
                "website_url": row.get("website_url", ""),
                "category": row.get("category", ""),
                "platform": row.get("platform", ""),
                "evidence": row.get("evidence", ""),
                "booking_url": row.get("booking_url", ""),
                "screenshot": row.get("screenshot", ""),
                "http_status": row.get("http_status", ""),
                "confidence": row.get("confidence", ""),
            })

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {JSON_PATH}")

    # Write HTML
    html_content = generate_html(sampled, counts, total_merchants)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Wrote {HTML_PATH}")

    # Summary
    total_samples = sum(len(v) for v in sampled.values())
    print(f"\nDone! {total_samples} samples across {len(CATEGORIES)} categories.")


if __name__ == "__main__":
    main()
