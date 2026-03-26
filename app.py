"""
Dogpile Ad Scraper — Web UI
Run: py app.py
Then open http://localhost:5000
"""

from flask import Flask, render_template_string, request, jsonify
import re
import requests as req_lib
from urllib.parse import urlparse
from scraper import fetch_ad_html, parse_all_ads

app = Flask(__name__)

# --- Contact enrichment helpers ---
_EMAIL_RE  = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
_MAILTO_RE = re.compile(r'href=["\']mailto:([\w.+-]+@[\w-]+\.[\w.]{2,})["\']', re.I)
_TEL_RE    = re.compile(r'href=["\']tel:([+\d\s().\-]{7,})["\']', re.I)
_PHONE_RE  = re.compile(r"\+?1?[\s.\-]?\(?(\d{3})\)?[\s.\-](\d{3})[\s.\-](\d{4})")
_SKIP_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js", ".woff", ".ttf", ".ico"}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _fetch_text(url: str) -> str:
    try:
        r = req_lib.get(url, headers={"User-Agent": _UA}, timeout=8, allow_redirects=True)
        return r.text if r.ok else ""
    except Exception:
        return ""


def _extract_contacts(text: str):
    emails: set = set()
    phones: set = set()
    for e in _MAILTO_RE.findall(text):
        emails.add(e.lower())
    for raw in _TEL_RE.findall(text):
        clean = re.sub(r"[^\d+]", "", raw)
        if len(clean) >= 10:
            phones.add(raw.strip())
    if not emails:
        for e in _EMAIL_RE.findall(text):
            if not any(e.endswith(x) for x in _SKIP_EXTS):
                emails.add(e.lower())
    if not phones:
        for m in _PHONE_RE.finditer(text):
            phones.add(f"({m.group(1)}) {m.group(2)}-{m.group(3)}")
    return emails, phones


HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dogpile Ad Scraper</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f5f5f5; color: #222; }
  header { background: #1a1a2e; color: #fff; padding: 16px 32px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 1.3rem; font-weight: 600; }
  .tag { background: #e94560; color: #fff; font-size: .7rem; padding: 2px 8px; border-radius: 99px; font-weight: 700; letter-spacing: .04em; }
  main { max-width: 1600px; margin: 28px auto; padding: 0 20px; }

  /* Input panel */
  .input-panel { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
  .input-panel label { display: block; font-weight: 600; font-size: .9rem; margin-bottom: 8px; color: #1a1a2e; }
  .input-panel .hint { font-size: .78rem; color: #888; margin-bottom: 10px; }
  textarea#keywords { width: 100%; height: 130px; padding: 10px 14px; border: 1px solid #ccc; border-radius: 6px; font-size: .9rem; font-family: inherit; resize: vertical; outline: none; line-height: 1.6; }
  textarea#keywords:focus { border-color: #1a1a2e; }
  .btn-row { display: flex; gap: 10px; margin-top: 12px; align-items: center; }
  .btn-run  { padding: 10px 26px; background: #e94560; color: #fff; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; font-weight: 600; }
  .btn-run:disabled { opacity: .45; cursor: not-allowed; }
  .btn-stop { padding: 10px 20px; background: #fff; color: #c0392b; border: 2px solid #c0392b; border-radius: 6px; font-size: 1rem; cursor: pointer; font-weight: 600; display: none; }
  .btn-stop:disabled { opacity: .5; cursor: not-allowed; }
  .kw-hint { font-size: .82rem; color: #888; margin-left: 4px; }

  /* Progress */
  .progress-panel { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; display: none; }
  .progress-top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
  .progress-kw { font-size: .9rem; font-weight: 600; color: #1a1a2e; }
  .progress-fraction { font-size: .82rem; color: #888; }
  .progress-track { height: 6px; background: #eee; border-radius: 99px; overflow: hidden; margin-bottom: 10px; }
  .progress-fill  { height: 100%; background: #e94560; border-radius: 99px; width: 0%; transition: width .3s ease; }
  .progress-sub { font-size: .8rem; color: #777; min-height: 18px; display: flex; align-items: center; gap: 6px; }
  .spinner    { display: inline-block; width: 14px; height: 14px; border: 2px solid #ccc; border-top-color: #1a1a2e; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: 6px; }
  .spinner-sm { display: inline-block; width: 10px; height: 10px; border: 2px solid #ddd; border-top-color: #888; border-radius: 50%; animation: spin .7s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Status / toolbar */
  #status { font-size: .9rem; color: #666; margin-bottom: 12px; min-height: 20px; }
  #status.error { color: #c0392b; }
  .toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
  .toolbar label { font-size: .85rem; color: #555; }
  .toolbar select { padding: 5px 10px; border: 1px solid #ccc; border-radius: 5px; font-size: .85rem; }
  .toolbar button { padding: 6px 14px; border: 1px solid #bbb; border-radius: 5px; background: #fff; cursor: pointer; font-size: .85rem; }
  .toolbar button:hover { background: #f0f0f0; }
  #count { font-size: .85rem; color: #888; margin-left: auto; }
  .empty { text-align: center; color: #999; padding: 60px 0; font-size: 1rem; }

  /* Table */
  .tbl-wrap { overflow-x: auto; border-radius: 8px; border: 1px solid #e0e0e0; background: #fff; }
  table { width: 100%; border-collapse: collapse; font-size: .875rem; }
  thead th { background: #1a1a2e; color: #fff; text-align: left; padding: 10px 14px; font-weight: 600; white-space: nowrap; font-size: .8rem; letter-spacing: .03em; text-transform: uppercase; }
  tbody tr { border-bottom: 1px solid #f0f0f0; }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: #fafafa; }
  td { padding: 10px 14px; vertical-align: top; }
  td.tc { text-align: center; }

  /* Column widths */
  .col-company { min-width: 160px; }
  .col-url     { min-width: 180px; }
  .col-email   { min-width: 200px; }
  .col-phone   { min-width: 150px; }

  .badge { display: inline-block; font-size: .68rem; font-weight: 700; padding: 2px 7px; border-radius: 99px; white-space: nowrap; }
  .badge-text    { background: #e8f4fd; color: #1565c0; }
  .badge-product { background: #e8f7ee; color: #2e7d32; }
  .kw-badge { display: inline-block; font-size: .72rem; background: #f3f0ff; color: #5e35b1; padding: 2px 7px; border-radius: 4px; word-break: break-word; line-height: 1.4; }
  .pos-num { font-size: .8rem; color: #aaa; font-weight: 600; }
  .company-link { color: #1565c0; text-decoration: none; font-weight: 600; }
  .company-link:hover { text-decoration: underline; }
  .company-plain { font-weight: 600; color: #333; }
  .display-url { font-size: .75rem; color: #2e7d32; word-break: break-all; }
  .headline { font-weight: 500; color: #1a1a2e; line-height: 1.4; }
  .price { font-weight: 700; color: #e94560; }
  .desc { color: #555; line-height: 1.5; }
  .sitelinks { display: flex; flex-wrap: wrap; gap: 4px; }
  .sitelink { font-size: .74rem; background: #f0f4ff; color: #1565c0; padding: 2px 7px; border-radius: 4px; }
  .contact-email { font-size: .78rem; color: #1a56a8; word-break: break-all; margin-bottom: 3px; }
  .contact-email::before { content: "\\2709\\A0"; }
  .contact-phone { font-size: .78rem; color: #2e7d32; margin-bottom: 3px; }
  .contact-phone::before { content: "\\260E\\A0"; }
  .contact-none { font-size: .78rem; color: #ccc; }
</style>
</head>
<body>
<header>
  <h1>Dogpile Ad Scraper</h1>
  <span class="tag">SPONSORED</span>
</header>
<main>

  <!-- Keyword input -->
  <div class="input-panel">
    <label for="keywords">Keywords</label>
    <div class="hint">One keyword per line. The scraper will work through them sequentially.</div>
    <textarea id="keywords" placeholder="running shoes&#10;mens shirts&#10;bluetooth headphones&#10;office chairs"></textarea>
    <div class="btn-row">
      <button class="btn-run" id="run-btn" onclick="startBatch()">Run Scraper</button>
      <button class="btn-stop" id="stop-btn" onclick="stopBatch()">Stop</button>
      <span class="kw-hint" id="kw-hint"></span>
    </div>
  </div>

  <!-- Progress -->
  <div class="progress-panel" id="progress-panel">
    <div class="progress-top">
      <span class="progress-kw" id="progress-kw">Starting…</span>
      <span class="progress-fraction" id="progress-fraction"></span>
    </div>
    <div class="progress-track"><div class="progress-fill" id="progress-fill"></div></div>
    <div class="progress-sub" id="progress-sub"></div>
  </div>

  <div id="status"></div>

  <div id="controls" style="display:none">
    <div class="toolbar">
      <label>Keyword:</label>
      <select id="kw-filter" onchange="renderTable()">
        <option value="all">All keywords</option>
      </select>
      <button onclick="exportJSON()">&#8595; JSON</button>
      <button onclick="exportCSV()">&#8595; CSV</button>
      <span id="count"></span>
    </div>
  </div>

  <div id="results"></div>
</main>

<script>
let currentAds = [];          // all ads across all keywords
let currentEnrichment = {};   // _uid -> {emails, phones}
let uidCounter = 0;
let stopRequested = false;
let batchRunning = false;
let batchErrors = [];         // keywords that failed and why

// Update keyword hint on textarea input
document.getElementById('keywords').addEventListener('input', updateKwHint);

function updateKwHint() {
  const kws = parseKeywords();
  const el = document.getElementById('kw-hint');
  el.textContent = kws.length ? kws.length + ' keyword' + (kws.length > 1 ? 's' : '') : '';
}

function parseKeywords() {
  return document.getElementById('keywords').value
    .split('\\n').map(k => k.trim()).filter(Boolean);
}

async function startBatch() {
  const keywords = parseKeywords();
  if (!keywords.length) return;

  // Reset state
  currentAds = [];
  currentEnrichment = {};
  batchErrors = [];
  uidCounter = 0;
  stopRequested = false;
  batchRunning = true;

  document.getElementById('run-btn').disabled = true;
  document.getElementById('stop-btn').style.display = '';
  document.getElementById('stop-btn').disabled = false;
  document.getElementById('stop-btn').textContent = 'Stop';
  document.getElementById('controls').style.display = 'none';
  document.getElementById('results').innerHTML = '';
  document.getElementById('status').textContent = '';
  document.getElementById('progress-panel').style.display = '';
  resetKwFilter();
  setProgress(0, keywords.length, '');

  let done = 0;
  for (const kw of keywords) {
    if (stopRequested) break;
    setProgress(done, keywords.length, kw);
    await processKeyword(kw, done, keywords.length);
    done++;
    setProgress(done, keywords.length, null);
  }

  batchRunning = false;
  document.getElementById('run-btn').disabled = false;
  document.getElementById('stop-btn').style.display = 'none';
  document.getElementById('progress-panel').style.display = 'none';

  const stopped = stopRequested ? ' (stopped early)' : '';
  let statusHtml = '';
  if (currentAds.length) {
    const uniqueKws = [...new Set(currentAds.map(a => a.keyword))].length;
    statusHtml = 'Found <strong>' + currentAds.length + '</strong> ads across <strong>'
      + uniqueKws + '</strong> keyword' + (uniqueKws > 1 ? 's' : '') + stopped + '.';
  } else {
    statusHtml = 'No ads found' + stopped + '.';
  }
  if (batchErrors.length) {
    statusHtml += ' <span style="color:#c0392b">\u26a0\ufe0f '
      + batchErrors.length + ' keyword' + (batchErrors.length > 1 ? 's' : '') + ' failed'
      + ' \u2014 likely a Cloudflare block. Try again or use a VPN.</span>';
  }
  setStatus(statusHtml);
}

function stopBatch() {
  stopRequested = true;
  document.getElementById('stop-btn').disabled = true;
  document.getElementById('stop-btn').textContent = 'Stopping\u2026';
  setProgressSub('<span class="spinner-sm"></span> Finishing current keyword then stopping\u2026');
}

async function processKeyword(kw, doneIdx, total) {
  setProgressSub('<span class="spinner"></span>Scraping\u2026');
  try {
    const resp = await fetch('/scrape', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query: kw})
    });
    const data = await resp.json();
    if (!resp.ok) {
      batchErrors.push('"' + kw + '": ' + (data.error || 'HTTP ' + resp.status));
      setProgressSub('\u26a0\ufe0f ' + (data.error || 'failed') + ' \u2014 skipping');
      return;
    }

    // Tag each ad with keyword and a batch-unique uid
    const newAds = data.ads.map(ad => {
      ad._uid = uidCounter++;
      ad.keyword = kw;
      return ad;
    });
    currentAds.push(...newAds);
    addToKwFilter(kw);
    document.getElementById('controls').style.display = '';
    renderTable();

    // Enrich concurrently for this keyword's ads
    if (newAds.length) {
      let enriched = 0;
      const toEnrich = newAds.filter(a => a.display_url);
      setProgressSub('<span class="spinner-sm"></span> Fetching contact info\u2026 0\u202f/\u202f' + toEnrich.length);

      // Mark ads with no display_url
      newAds.filter(a => !a.display_url).forEach(ad => {
        currentEnrichment[ad._uid] = {emails: [], phones: []};
        const ec = document.getElementById('contact-email-' + ad._uid);
        const pc = document.getElementById('contact-phone-' + ad._uid);
        if (ec) ec.innerHTML = '<span class="contact-none">\u2014</span>';
        if (pc) pc.innerHTML = '<span class="contact-none">\u2014</span>';
      });

      await Promise.all(toEnrich.map(async ad => {
        await enrichOne(ad);
        enriched++;
        setProgressSub('<span class="spinner-sm"></span> Fetching contact info\u2026 '
          + enriched + '\u202f/\u202f' + toEnrich.length);
      }));
    }
  } catch (err) {
    setProgressSub('Error on "' + kw + '": ' + err.message);
  }
}

async function enrichOne(ad) {
  try {
    const resp = await fetch('/enrich', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({display_url: ad.display_url})
    });
    const data = await resp.json();
    currentEnrichment[ad._uid] = data;
  } catch (_) {
    currentEnrichment[ad._uid] = {emails: [], phones: []};
  }
  const data = currentEnrichment[ad._uid];
  const ec = document.getElementById('contact-email-' + ad._uid);
  const pc = document.getElementById('contact-phone-' + ad._uid);
  if (ec) ec.innerHTML = renderEmails(data);
  if (pc) pc.innerHTML = renderPhones(data);
}

// ---- Progress helpers ----
function setProgress(done, total, currentKw) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('progress-fraction').textContent = done + '\u202f/\u202f' + total + ' done';
  if (currentKw !== null) {
    document.getElementById('progress-kw').textContent = '\u201c' + currentKw + '\u201d';
  } else {
    document.getElementById('progress-kw').textContent = done < total ? 'Next keyword\u2026' : 'Done';
  }
}
function setProgressSub(html) {
  document.getElementById('progress-sub').innerHTML = html;
}

// ---- Keyword filter helpers ----
function resetKwFilter() {
  const sel = document.getElementById('kw-filter');
  sel.innerHTML = '<option value="all">All keywords</option>';
}
function addToKwFilter(kw) {
  const sel = document.getElementById('kw-filter');
  if ([...sel.options].some(o => o.value === kw)) return;
  const opt = document.createElement('option');
  opt.value = kw; opt.textContent = kw;
  sel.appendChild(opt);
}

// ---- Table ----
function renderTable() {
  const kwFilter = document.getElementById('kw-filter').value;

  let ads = currentAds;
  if (kwFilter !== 'all') ads = ads.filter(a => a.keyword === kwFilter);

  // Deduplicate by company name — keep first occurrence of each advertiser
  const seenCompanies = new Set();
  ads = ads.filter(ad => {
    const key = (ad.advertiser || '').toLowerCase().trim();
    if (key) {
      if (seenCompanies.has(key)) return false;
      seenCompanies.add(key);
    }
    return true;
  });

  document.getElementById('count').textContent = ads.length + ' result' + (ads.length !== 1 ? 's' : '');

  if (!ads.length) {
    document.getElementById('results').innerHTML = '<div class="empty">No ads yet\u2014results appear as each keyword finishes.</div>';
    return;
  }

  const rows = ads.map((ad, rowIdx) => {
    const companyCell = ad.click_url
      ? '<a class="company-link" href="' + escAttr(ad.click_url) + '" target="_blank" rel="noopener">'
          + escHtml(ad.advertiser || '\u2014') + '</a>'
      : '<span class="company-plain">' + escHtml(ad.advertiser || '\u2014') + '</span>';

    const urlCell = ad.display_url
      ? '<span class="display-url">' + escHtml(ad.display_url) + '</span>' : '';

    const cached = currentEnrichment[ad._uid];
    const spinner = '<span class="spinner-sm"></span>';
    const emailInner = cached !== undefined ? renderEmails(cached) : spinner;
    const phoneInner = cached !== undefined ? renderPhones(cached) : spinner;

    return '<tr>'
      + '<td class="col-company">' + companyCell + '</td>'
      + '<td class="col-url">' + urlCell + '</td>'
      + '<td class="col-email" id="contact-email-' + ad._uid + '">' + emailInner + '</td>'
      + '<td class="col-phone" id="contact-phone-' + ad._uid + '">' + phoneInner + '</td>'
      + '</tr>';
  }).join('');

  document.getElementById('results').innerHTML =
    '<div class="tbl-wrap"><table>'
    + '<thead><tr>'
    + '<th class="col-company">Advertiser</th>'
    + '<th class="col-url">Display URL</th>'
    + '<th class="col-email">Emails</th>'
    + '<th class="col-phone">Phones</th>'
    + '</tr></thead>'
    + '<tbody>' + rows + '</tbody>'
    + '</table></div>';
}

function renderEmails(data) {
  if (data.emails && data.emails.length)
    return data.emails.map(e => '<div class="contact-email">' + escHtml(e) + '</div>').join('');
  return '<span class="contact-none">\u2014</span>';
}
function renderPhones(data) {
  if (data.phones && data.phones.length)
    return data.phones.map(p => '<div class="contact-phone">' + escHtml(p) + '</div>').join('');
  return '<span class="contact-none">\u2014</span>';
}

// ---- Utilities ----
function setStatus(html) {
  document.getElementById('status').innerHTML = html;
}
function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s) {
  return String(s||'').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ---- Exports ----
function exportJSON() {
  const ads = currentAds.map(ad => {
    const enrich = currentEnrichment[ad._uid] || {};
    const {_uid, ...rest} = ad;
    return {...rest, emails: enrich.emails || [], phones: enrich.phones || []};
  });
  const blob = new Blob([JSON.stringify({ad_count: ads.length, ads}, null, 2)], {type: 'application/json'});
  download(blob, 'dogpile_batch_ads.json');
}

function exportCSV() {
  const fields = ['keyword','position','ad_type','advertiser','display_url','headline','price','description','click_url','sitelinks','emails','phones'];
  const rows = [fields.join(',')];
  for (const ad of currentAds) {
    const enrich = currentEnrichment[ad._uid] || {};
    rows.push(fields.map(f => {
      let v;
      if (f === 'sitelinks') v = (ad.sitelinks||[]).map(s=>s.text).join(' | ');
      else if (f === 'emails') v = (enrich.emails||[]).join(' | ');
      else if (f === 'phones') v = (enrich.phones||[]).join(' | ');
      else v = ad[f] || '';
      return '"' + String(v).replace(/"/g,'""') + '"';
    }).join(','));
  }
  download(new Blob([rows.join('\\n')], {type: 'text/csv'}), 'dogpile_batch_ads.csv');
}

function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
}

// Init hint
updateKwHint();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json()
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    try:
        ad_htmls = fetch_ad_html(query, headless=False)
    except Exception as e:
        return jsonify({"error": f"Scraper error: {e}"}), 500

    if not ad_htmls:
        return jsonify({"error": "No ads found — page may not have loaded."}), 502

    ads = parse_all_ads(ad_htmls)
    return jsonify({"query": query, "ad_count": len(ads), "ads": ads})


@app.route("/enrich", methods=["POST"])
def enrich():
    data = request.get_json()
    display_url = (data.get("display_url") or "").strip()
    if not display_url:
        return jsonify({"emails": [], "phones": []})

    raw = display_url if display_url.startswith("http") else "https://" + display_url
    parsed = urlparse(raw)
    base = f"{parsed.scheme}://{parsed.netloc}"

    emails: set = set()
    phones: set = set()
    for path in ["", "/contact", "/contact-us", "/about", "/about-us"]:
        text = _fetch_text(base + path)
        if text:
            e, p = _extract_contacts(text)
            emails |= e
            phones |= p
        if emails or phones:
            break

    return jsonify({"emails": sorted(emails)[:5], "phones": sorted(phones)[:5]})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5002))
    app.run(debug=False, port=port, threaded=True)
