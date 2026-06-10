#!/usr/bin/env python3
"""
Fetch the latest 13F-HR for each resolved manager and parse holdings.

For each manager with a CIK:
  1. Pull https://data.sec.gov/submissions/CIK##########.json
  2. Find the most recent 13F-HR (and 13F-HR/A amendments)
  3. Download the filing's information table XML
  4. Parse holdings -> data/holdings/{slug}.json

Also keeps the prior snapshot (if any) as {slug}.prev.json so the site
builder can compute adds / exits / increases / decreases.

Usage:
    SEC_CONTACT="Your Name your@email.com" python scripts/fetch_13fs.py

Notes:
  - Since the Jan 2023 EDGAR technical spec change, <value> is reported in
    whole dollars (previously thousands). All current filings are dollars.
  - 13Fs cover US-listed long positions only; filed up to 45 days after
    quarter end.
"""

import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANAGERS_PATH = ROOT / "data" / "managers.json"
HOLDINGS_DIR = ROOT / "data" / "holdings"
HOLDINGS_DIR.mkdir(parents=True, exist_ok=True)

SEC_CONTACT = os.environ.get("SEC_CONTACT")
if not SEC_CONTACT:
    sys.exit("Set SEC_CONTACT env var, e.g. SEC_CONTACT='Arthur arthur@example.com'")

HEADERS = {"User-Agent": SEC_CONTACT, "Accept-Encoding": "gzip, deflate"}
PAUSE = 0.2  # stay well under SEC's 10 req/s limit


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            data = gzip.decompress(data)
        return data


def get_json(url: str):
    return json.loads(get(url))


def latest_13f(cik: str):
    """Return (accession_no, report_date, filing_date) of newest 13F-HR."""
    subs = get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    recent = subs["filings"]["recent"]
    best = None
    for form, acc, rdate, fdate in zip(
        recent["form"], recent["accessionNumber"],
        recent["reportDate"], recent["filingDate"],
    ):
        if form in ("13F-HR", "13F-HR/A"):
            key = (rdate, fdate)  # newest period, then newest filing (amendments win)
            if best is None or key > best[0]:
                best = (key, acc, rdate, fdate)
    if best is None:
        return None
    _, acc, rdate, fdate = best
    return acc, rdate, fdate


def info_table_url(cik: str, accession: str):
    acc_nodash = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}"
    index = get_json(f"{base}/index.json")
    xml_files = [
        f["name"] for f in index["directory"]["item"]
        if f["name"].lower().endswith(".xml")
        and "primary_doc" not in f["name"].lower()
    ]
    # Prefer files that look like the info table
    xml_files.sort(key=lambda n: ("infotable" not in n.lower(), n))
    for name in xml_files:
        return f"{base}/{name}"
    return None


def parse_info_table(xml_bytes: bytes):
    """Parse holdings ignoring XML namespaces."""
    root = ET.fromstring(xml_bytes)

    def local(tag):
        return tag.rsplit("}", 1)[-1]

    holdings = []
    for el in root.iter():
        if local(el.tag) != "infoTable":
            continue
        row = {}
        for child in el.iter():
            t = local(child.tag)
            txt = (child.text or "").strip()
            if t == "nameOfIssuer":
                row["issuer"] = txt
            elif t == "titleOfClass":
                row["class"] = txt
            elif t == "cusip":
                row["cusip"] = txt
            elif t == "value":
                row["value"] = int(float(txt or 0))
            elif t == "sshPrnamt":
                row["shares"] = int(float(txt or 0))
            elif t == "sshPrnamtType":
                row["shares_type"] = txt
            elif t == "putCall":
                row["put_call"] = txt
        if row.get("cusip"):
            holdings.append(row)

    # Merge duplicate CUSIP lines (multiple managers/discretion splits)
    merged = {}
    for h in holdings:
        key = (h["cusip"], h.get("put_call", ""))
        if key in merged:
            merged[key]["value"] += h.get("value", 0)
            merged[key]["shares"] = merged[key].get("shares", 0) + h.get("shares", 0)
        else:
            merged[key] = dict(h)
    out = sorted(merged.values(), key=lambda h: -h.get("value", 0))
    total = sum(h.get("value", 0) for h in out) or 1
    for h in out:
        h["pct_of_portfolio"] = round(100 * h.get("value", 0) / total, 2)
    return out


def main():
    data = json.loads(MANAGERS_PATH.read_text())
    for mgr in data["managers"]:
        cik = mgr.get("cik")
        if not cik:
            print(f"[SKIP] {mgr['name']} — no CIK (run resolve_ciks.py first)")
            continue
        try:
            meta = latest_13f(cik)
            time.sleep(PAUSE)
            if not meta:
                print(f"[MISS] {mgr['name']} — no 13F-HR on file")
                continue
            accession, report_date, filing_date = meta

            out_path = HOLDINGS_DIR / f"{mgr['slug']}.json"
            if out_path.exists():
                prev = json.loads(out_path.read_text())
                if prev.get("accession") == accession:
                    print(f"[OK]   {mgr['name']} — up to date ({report_date})")
                    continue
                # rotate snapshot for QoQ diffing
                (HOLDINGS_DIR / f"{mgr['slug']}.prev.json").write_text(
                    json.dumps(prev, indent=2)
                )

            url = info_table_url(cik, accession)
            time.sleep(PAUSE)
            if not url:
                print(f"[MISS] {mgr['name']} — info table not found in {accession}")
                continue
            holdings = parse_info_table(get(url))
            time.sleep(PAUSE)

            snapshot = {
                "slug": mgr["slug"],
                "name": mgr["name"],
                "cik": cik,
                "accession": accession,
                "report_date": report_date,
                "filing_date": filing_date,
                "total_value": sum(h.get("value", 0) for h in holdings),
                "num_positions": len(holdings),
                "holdings": holdings,
            }
            out_path.write_text(json.dumps(snapshot, indent=2))
            print(f"[NEW]  {mgr['name']} — {len(holdings)} positions, "
                  f"period {report_date}, filed {filing_date}")
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {mgr['name']}: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    main()
