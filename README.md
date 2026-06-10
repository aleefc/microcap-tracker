# Microholdings — a Dataroma for microcap funds

Tracks the 13F portfolios of 20 concentrated small/microcap managers,
builds per-manager portfolio pages, quarter-over-quarter change tracking,
and a consensus-ownership view.

## Quick start

Requires Python 3.9+ (standard library only — no pip installs).

```bash
export SEC_CONTACT="Your Name your@email.com"   # required by SEC fair-access policy

python scripts/resolve_ciks.py    # 1. map manager names -> EDGAR CIKs
python scripts/fetch_13fs.py      # 2. download + parse latest 13F-HR per manager
python scripts/build_site.py      # 3. generate static site

python -m http.server -d site     # browse at http://localhost:8000
```

Re-run steps 2–3 each quarter (filing deadline is 45 days after quarter
end — most filings land Feb 14, May 15, Aug 14, Nov 14). The fetcher
rotates the prior snapshot to `*.prev.json` so the site shows NEW / SOLD
OUT / share-count changes automatically after the second run.

## Reviewing CIK resolution

`resolve_ciks.py` prints `[CHECK]` when several EDGAR entities match a
name — eyeball those and fix `cik` in `data/managers.json` if it picked
the wrong one (similarly-named RIAs are common). Entries it can't find get
`[MISS]`; adjust `edgar_search_name` and re-run. Two known quirks:

- **Robotti** files under "ROBOTTI ROBERT" (the individual), already set
  as the search name.
- **Harbert Discovery Fund** filings come through Harbert Fund Advisors /
  Harbert Management entities — review the candidates.

## Data notes

- 13F values are whole dollars for all current filings (EDGAR spec change,
  Jan 2023). Pre-2023 filings report in thousands — relevant only if you
  backfill history.
- 13Fs cover US-listed longs (plus options) only. No shorts, no cash, no
  foreign lines. Filed up to 45 days late.
- Duplicate CUSIP rows within a filing (shared-discretion splits) are
  merged.
- Put/call option lines are tagged and excluded from consensus.

## Roadmap (ordered by value-per-effort)

1. **CUSIP -> ticker mapping** via OpenFIGI (free API key) so pages link to
   quotes and you can join prices.
2. **History backfill**: loop older accessions per CIK to build multi-year
   position histories and a Dataroma-style "buy history" per stock.
3. **Clone-performance ranking**: price each manager's disclosed portfolio
   forward from the filing date (not period date) to rank which managers'
   13Fs are actually worth following — your "best performing" filter,
   computed honestly.
4. **13D/G + Form 4 overlay**: you already parse Form 4s for your insider
   app — merging activist stakes and insider cluster-buys with 13F
   consensus is the killer feature Dataroma doesn't have.
5. **Automation**: GitHub Actions cron (same pattern as your EDGAR daily
   digest) on the filing-deadline weeks; deploy `site/` to GitHub Pages.
6. Graduate to Next.js + Postgres once the static version proves out the
   data model.

## Layout

```
data/managers.json        seed list of 20 managers (edit freely)
data/holdings/*.json      latest parsed 13F per manager (+ .prev.json)
scripts/resolve_ciks.py   name -> CIK resolution against EDGAR
scripts/fetch_13fs.py     13F-HR download + info-table parser
scripts/build_site.py     static site generator -> site/
```
