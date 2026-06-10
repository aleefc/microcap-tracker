#!/usr/bin/env python3
"""
Resolve each manager in data/managers.json to an SEC EDGAR CIK.

Uses EDGAR's company search (atom output), filtered to entities that have
filed 13F-HR. Writes resolved CIKs back into managers.json and prints any
ambiguous matches for manual review.

Usage:
    SEC_CONTACT="Your Name your@email.com" python scripts/resolve_ciks.py

SEC requires a descriptive User-Agent with contact info, and asks for
<= 10 requests/second. We stay well under that.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANAGERS_PATH = ROOT / "data" / "managers.json"

SEC_CONTACT = os.environ.get("SEC_CONTACT")
if not SEC_CONTACT:
    sys.exit("Set SEC_CONTACT env var, e.g. SEC_CONTACT='Arthur arthur@example.com'")

HEADERS = {"User-Agent": SEC_CONTACT, "Accept-Encoding": "gzip, deflate"}
SEARCH_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&company={query}&type=13F-HR&dateb=&owner=include"
    "&count=20&output=atom"
)
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            data = gzip.decompress(data)
        return data


def search_entities(name: str):
    """Return list of (cik, company_name) candidates that have filed 13F-HR."""
    url = SEARCH_URL.format(query=urllib.parse.quote(name))
    raw = fetch(url)
    candidates = []

    # Case 1: multiple results -> atom feed with <entry> elements
    # Case 2: single exact match -> EDGAR redirects to that company's filing
    #         list (atom with <company-info>)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return candidates

    # Single-company response
    for info in root.iter():
        if info.tag.endswith("company-info"):
            cik = name_ = None
            for child in info.iter():
                if child.tag.endswith("cik"):
                    cik = child.text
                elif child.tag.endswith("conformed-name"):
                    name_ = child.text
            if cik:
                candidates.append((cik.lstrip("0"), name_ or name))
            return candidates

    # Multi-company response
    for entry in root.findall("a:entry", ATOM_NS):
        title = entry.findtext("a:title", default="", namespaces=ATOM_NS)
        link = entry.find("a:link", ATOM_NS)
        href = link.get("href") if link is not None else ""
        m = re.search(r"CIK=(\d+)", href)
        if m:
            candidates.append((m.group(1).lstrip("0"), title))
    return candidates


def main():
    data = json.loads(MANAGERS_PATH.read_text())
    unresolved = []

    for mgr in data["managers"]:
        if mgr.get("cik"):
            continue
        query = mgr.get("edgar_search_name") or mgr["name"]
        try:
            candidates = search_entities(query)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {mgr['name']}: {exc}")
            unresolved.append(mgr["name"])
            time.sleep(0.5)
            continue

        if len(candidates) == 1:
            cik, ename = candidates[0]
            mgr["cik"] = cik
            mgr["edgar_entity_name"] = ename
            print(f"[OK]    {mgr['name']:<45} CIK {cik}  ({ename})")
        elif len(candidates) > 1:
            # Take the first, but flag for review — EDGAR ranks exact-ish
            # matches first. Review the printed alternatives.
            cik, ename = candidates[0]
            mgr["cik"] = cik
            mgr["edgar_entity_name"] = ename
            mgr["cik_needs_review"] = True
            print(f"[CHECK] {mgr['name']:<45} picked CIK {cik} ({ename})")
            for alt_cik, alt_name in candidates[1:5]:
                print(f"         alt: CIK {alt_cik}  {alt_name}")
        else:
            unresolved.append(mgr["name"])
            print(f"[MISS]  {mgr['name']:<45} no 13F-HR filer found for '{query}'")

        time.sleep(0.2)

    MANAGERS_PATH.write_text(json.dumps(data, indent=2))
    print(f"\nWrote {MANAGERS_PATH}")
    if unresolved:
        print("Unresolved (try a different edgar_search_name, or check at "
              "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany):")
        for n in unresolved:
            print(f"  - {n}")


if __name__ == "__main__":
    main()
