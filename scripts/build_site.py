#!/usr/bin/env python3
"""
Build a static Dataroma-style site from data/holdings/*.json.

Outputs to site/:
  index.html            manager grid + consensus snapshot
  consensus.html        every security held by 2+ managers
  managers/{slug}.html  full portfolio per manager, with QoQ changes

Usage:
    python scripts/build_site.py
Then open site/index.html, or `python -m http.server -d site`.
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_DIR = ROOT / "data" / "holdings"
SITE = ROOT / "site"
(SITE / "managers").mkdir(parents=True, exist_ok=True)

MANAGERS = json.loads((ROOT / "data" / "managers.json").read_text())["managers"]


def esc(s):
    return html.escape(str(s if s is not None else ""))


def money(v):
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:,.2f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:,.1f}M"
    return f"${v:,.0f}"


CSS = """
:root{
  --paper:#F6F7F4; --ink:#1A2420; --muted:#5C6B64; --line:#D8DDD8;
  --moss:#1E6B4E; --moss-soft:#E3EEE8; --rust:#A8432B; --rust-soft:#F4E6E0;
  --card:#FFFFFF;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif}
a{color:var(--moss);text-decoration:none}
a:hover{text-decoration:underline}
a:focus-visible{outline:2px solid var(--moss);outline-offset:2px}
header{border-bottom:3px solid var(--ink);padding:28px 32px 18px;
  display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px}
.brand{font-family:"Archivo",sans-serif;font-weight:800;font-size:26px;
  letter-spacing:-.02em}
.brand .micro{color:var(--moss)}
nav a{margin-left:22px;font-weight:600;font-size:14px;color:var(--ink);
  text-transform:uppercase;letter-spacing:.06em}
main{max-width:1100px;margin:0 auto;padding:28px 32px 80px}
h1{font-family:"Archivo",sans-serif;font-weight:800;font-size:32px;
  letter-spacing:-.02em;margin:6px 0 4px}
.sub{color:var(--muted);margin:0 0 24px;font-size:14px}
table{width:100%;border-collapse:collapse;background:var(--card);
  border:1px solid var(--line)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted);text-align:left;padding:10px 12px;
  border-bottom:2px solid var(--ink);background:var(--card);
  position:sticky;top:0}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:hover td{background:var(--moss-soft)}
.num{font-family:"IBM Plex Mono",monospace;font-size:13.5px;
  text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.style{color:var(--muted);font-size:13px}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;
  border-radius:3px;letter-spacing:.04em}
.tag.new{background:var(--moss-soft);color:var(--moss)}
.tag.exit{background:var(--rust-soft);color:var(--rust)}
.tag.put{background:var(--rust-soft);color:var(--rust)}
.depth{font-family:"IBM Plex Mono",monospace;color:var(--moss);
  letter-spacing:2px;font-size:12px}
.depth .off{color:var(--line)}
.bar{height:5px;background:var(--moss);min-width:2px;border-radius:2px}
.barwrap{width:110px;background:#EBEEEA;border-radius:2px}
footer{max-width:1100px;margin:0 auto;padding:0 32px 40px;
  color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);
  padding-top:16px}
@media (max-width:720px){
  header,main{padding-left:16px;padding-right:16px}
  .style{display:none}
}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800'
         '&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono&display=swap" '
         'rel="stylesheet">')


def page(title, body, depth=""):
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>{FONTS}<style>{CSS}</style></head><body>
<header><div class="brand"><span class="micro">micro</span>holdings</div>
<nav><a href="{depth}index.html">Managers</a>
<a href="{depth}consensus.html">Consensus</a></nav></header>
<main>{body}</main>
<footer>Source: SEC EDGAR 13F-HR filings. 13Fs disclose US-listed long
positions only, filed up to 45 days after quarter end. Nothing here is
investment advice.</footer></body></html>"""


def load_snapshots():
    snaps = {}
    for mgr in MANAGERS:
        p = HOLDINGS_DIR / f"{mgr['slug']}.json"
        if p.exists():
            snaps[mgr["slug"]] = json.loads(p.read_text())
    return snaps


def load_prev(slug):
    p = HOLDINGS_DIR / f"{slug}.prev.json"
    return json.loads(p.read_text()) if p.exists() else None


def build_consensus(snaps):
    by_cusip = {}
    for slug, snap in snaps.items():
        for h in snap["holdings"]:
            if h.get("put_call"):
                continue  # options aren't conviction longs
            c = by_cusip.setdefault(h["cusip"], {
                "issuer": h["issuer"], "cusip": h["cusip"],
                "holders": [], "total_value": 0,
            })
            c["holders"].append({
                "slug": slug, "name": snap["name"],
                "pct": h["pct_of_portfolio"], "value": h["value"],
            })
            c["total_value"] += h.get("value", 0)
    rows = [c for c in by_cusip.values() if len(c["holders"]) >= 2]
    rows.sort(key=lambda c: (-len(c["holders"]), -c["total_value"]))
    return rows


def depth_dots(n, total):
    on = "●" * n
    off = f'<span class="off">{"○" * max(0, min(total, 8) - n)}</span>'
    return f'<span class="depth" title="{n} of {total} managers">{on}{off}</span>'


def build_index(snaps, consensus):
    rows = []
    for mgr in MANAGERS:
        snap = snaps.get(mgr["slug"])
        if snap:
            top = snap["holdings"][0] if snap["holdings"] else None
            rows.append(f"""<tr>
<td><a href="managers/{mgr['slug']}.html"><strong>{esc(mgr['name'])}</strong></a><br>
<span class="style">{esc(mgr['manager'])} — {esc(mgr['style'])}</span></td>
<td class="num">{money(snap['total_value'])}</td>
<td class="num">{snap['num_positions']}</td>
<td>{esc(top['issuer']) if top else '—'}
  <span class="num">{top['pct_of_portfolio']}%</span></td>
<td class="num">{esc(snap['report_date'])}</td></tr>""")
        else:
            rows.append(f"""<tr>
<td><strong>{esc(mgr['name'])}</strong><br>
<span class="style">{esc(mgr['manager'])} — {esc(mgr['style'])}</span></td>
<td class="num" colspan="4">no data yet — run fetch_13fs.py</td></tr>""")

    top_consensus = "".join(
        f"""<tr><td><strong>{esc(c['issuer'])}</strong>
<span class="style">{esc(c['cusip'])}</span></td>
<td>{depth_dots(len(c['holders']), len(snaps))}</td>
<td class="num">{money(c['total_value'])}</td></tr>"""
        for c in consensus[:10]
    )

    body = f"""<h1>Tracked managers</h1>
<p class="sub">{len(snaps)} of {len(MANAGERS)} portfolios loaded ·
concentrated small &amp; microcap 13F filers</p>
<table><thead><tr><th>Manager</th><th>13F value</th><th>Positions</th>
<th>Top holding</th><th>Period</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h1 style="margin-top:44px">Top consensus names</h1>
<p class="sub">Held by the most managers — <a href="consensus.html">full list</a></p>
<table><thead><tr><th>Security</th><th>Ownership depth</th><th>Combined value</th>
</tr></thead><tbody>{top_consensus or '<tr><td colspan=3>No overlap yet</td></tr>'}
</tbody></table>"""
    (SITE / "index.html").write_text(page("Microholdings — Managers", body))


def build_consensus_page(snaps, consensus):
    rows = []
    for c in consensus:
        holders = ", ".join(
            f'<a href="managers/{h["slug"]}.html">{esc(h["name"])}</a> '
            f'<span class="num">({h["pct"]}%)</span>'
            for h in sorted(c["holders"], key=lambda h: -h["pct"])
        )
        rows.append(f"""<tr><td><strong>{esc(c['issuer'])}</strong>
<span class="style">{esc(c['cusip'])}</span></td>
<td>{depth_dots(len(c['holders']), len(snaps))}</td>
<td class="num">{money(c['total_value'])}</td>
<td class="style">{holders}</td></tr>""")
    body = f"""<h1>Consensus ownership</h1>
<p class="sub">Securities held by two or more tracked managers, ranked by
number of holders. In microcap, overlap among concentrated managers is rare —
and worth investigating when it happens.</p>
<table><thead><tr><th>Security</th><th>Depth</th><th>Combined value</th>
<th>Held by (% of each portfolio)</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan=4>No overlap yet</td></tr>'}</tbody></table>"""
    (SITE / "consensus.html").write_text(page("Microholdings — Consensus", body))


def build_manager_pages(snaps):
    for mgr in MANAGERS:
        snap = snaps.get(mgr["slug"])
        if not snap:
            continue
        prev = load_prev(mgr["slug"])
        prev_by_cusip = {h["cusip"]: h for h in prev["holdings"]} if prev else {}
        cur_cusips = {h["cusip"] for h in snap["holdings"]}

        rows = []
        maxpct = max((h["pct_of_portfolio"] for h in snap["holdings"]), default=1) or 1
        for h in snap["holdings"]:
            tags = ""
            if h.get("put_call"):
                tags += f' <span class="tag put">{esc(h["put_call"]).upper()}</span>'
            change = ""
            if prev:
                p = prev_by_cusip.get(h["cusip"])
                if p is None:
                    tags += ' <span class="tag new">NEW</span>'
                elif p.get("shares"):
                    delta = (h.get("shares", 0) - p["shares"]) / p["shares"] * 100
                    if abs(delta) >= 0.5:
                        sign = "+" if delta > 0 else ""
                        change = f"{sign}{delta:,.0f}%"
            width = max(2, round(100 * h["pct_of_portfolio"] / maxpct))
            rows.append(f"""<tr>
<td><strong>{esc(h['issuer'])}</strong>{tags}<br>
<span class="style">{esc(h.get('class',''))} · {esc(h['cusip'])}</span></td>
<td class="num">{money(h.get('value',0))}</td>
<td class="num">{h.get('shares',0):,}</td>
<td class="num">{change or '·'}</td>
<td><div class="barwrap"><div class="bar" style="width:{width}%"></div></div>
<span class="num">{h['pct_of_portfolio']}%</span></td></tr>""")

        exits = ""
        if prev:
            gone = [h for h in prev["holdings"] if h["cusip"] not in cur_cusips]
            if gone:
                exits = ("<h1 style='margin-top:40px;font-size:22px'>Exited</h1><table>"
                         "<tbody>" + "".join(
                             f"<tr><td>{esc(h['issuer'])} "
                             f"<span class='tag exit'>SOLD OUT</span></td>"
                             f"<td class='num'>was {h['pct_of_portfolio']}%</td></tr>"
                             for h in gone) + "</tbody></table>")

        body = f"""<h1>{esc(mgr['name'])}</h1>
<p class="sub">{esc(mgr['manager'])} · {esc(mgr['style'])} ·
Period {esc(snap['report_date'])}, filed {esc(snap['filing_date'])} ·
{snap['num_positions']} positions · {money(snap['total_value'])} ·
<a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={esc(snap['cik'])}&type=13F&dateb=&owner=include&count=40">EDGAR</a></p>
<table><thead><tr><th>Security</th><th>Value</th><th>Shares</th>
<th>Δ shares QoQ</th><th>% of portfolio</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>{exits}"""
        (SITE / "managers" / f"{mgr['slug']}.html").write_text(
            page(f"Microholdings — {mgr['name']}", body, depth="../"))


def main():
    snaps = load_snapshots()
    consensus = build_consensus(snaps)
    build_index(snaps, consensus)
    build_consensus_page(snaps, consensus)
    build_manager_pages(snaps)
    print(f"Built site/ with {len(snaps)} manager portfolios "
          f"and {len(consensus)} consensus names.")


if __name__ == "__main__":
    main()
