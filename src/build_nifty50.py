"""Run the classification pipeline across every index constituent.

    python src/build_nifty50.py              # build everything, write the workbook
    python src/build_nifty50.py --unresolved # list what still needs research

One entity master is shared by all companies, so each company warms the cache
for the next: by the end of an index run most institutional holders resolve
without a single web call.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import build as pipeline
import build_register
import entity_master as em
from write_workbook import write as write_workbook

ROOT = Path(__file__).resolve().parent.parent
# The quarter every company is reported against unless its own filing says
# otherwise - the latest that had closed and been filed when this was built.
FALLBACK_QUARTER = "Jun/2026"


def load_index(path=ROOT / "data" / "nifty50.json"):
    return json.loads(Path(path).read_text())


def run(index, only=None):
    """Returns (companies, diagnostics)."""
    master = em.load()
    taxonomy = json.loads((ROOT / "data" / "taxonomy.json").read_text())
    categories = taxonomy["categories"]

    companies, diag = [], {"missing": [], "warnings": [], "promoter_issues": {}}
    for c in index["constituents"]:
        ticker = c["ticker"]
        if only and ticker not in only:
            continue
        if not (ROOT / "data" / "registers" / f"{ticker}.json").exists():
            # A constituent with no register still belongs in the workbook:
            # dropping it would quietly turn "the Nifty 50" into "the ones
            # that worked". It appears with no holders and says so.
            diag["missing"].append(ticker)
            companies.append({
                "ticker": ticker, "company": c["company_name"],
                "sector": c.get("sector"), "quarters": [FALLBACK_QUARTER],
                "rows": [],
                "meta": {"isin": None, "as_of": None, "shares_scrr": None,
                         "denominator_note": "no shareholding data retrieved",
                         "source_urls": [], "promoter_pct": None,
                         "reconciliation": "no data", "drift": None},
            })
            continue

        raw, registry = build_register.build(ticker)
        diag["warnings"] += build_register.check(raw, registry)
        rows, issues = pipeline.classify(raw["holders"], registry, ticker, master)
        if issues:
            diag["promoter_issues"][ticker] = issues

        companies.append({
            "ticker": ticker,
            "company": raw["company"],
            "sector": c.get("sector"),
            "quarters": raw["quarter_labels"],
            "rows": rows,
            "meta": {
                "isin": raw.get("isin"),
                "as_of": raw.get("as_of"),
                "shares_scrr": raw.get("shares_scrr"),
                "denominator_note": raw.get("denominator_note"),
                "source_urls": raw.get("source_urls", []),
                "promoter_pct": registry.get("promoter_total_pct"),
                "reconciliation": raw.get("promoter_reconciliation"),
                "drift": raw.get("promoter_drift"),
            },
        })

    em.save(master)
    return companies, categories, diag


def unresolved(companies):
    """Distinct holder names no pass could settle, with where they appear."""
    pending = defaultdict(lambda: {"tickers": [], "shares": 0})
    for c in companies:
        latest = c["quarters"][-1]
        for r in c["rows"]:
            if not (r["category"] is None or r.get("needs_review")):
                continue
            slot = pending[r["holder_name"]]
            if c["ticker"] not in slot["tickers"]:
                slot["tickers"].append(c["ticker"])
            slot["shares"] += r["quarters"].get(latest) or 0
    return dict(sorted(pending.items(), key=lambda kv: -kv[1]["shares"]))


def write_flat(companies, path):
    quarters = []
    for c in companies:
        for q in c["quarters"]:
            if q not in quarters:
                quarters.append(q)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Ticker", "Company name", "Share holder name",
                    "Share holder category"]
                   + [f"{q} No of shares" for q in quarters]
                   + ["Basis", "Confidence", "Country", "Entity type",
                      "Holding vehicle", "Review?", "Source"])
        for c in companies:
            for r in c["rows"]:
                w.writerow([c["ticker"], c["company"], r["holder_name"],
                            r["category"]]
                           + [r["quarters"].get(q) for q in quarters]
                           + [r.get("basis"), r.get("confidence"),
                              r.get("country"), r.get("entity_type"),
                              r.get("holding_vehicle"),
                              "REVIEW" if r.get("needs_review") else "",
                              r.get("source")])
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", action="store_true",
                    help="report what data exists per company, then stop")
    ap.add_argument("--unresolved", action="store_true",
                    help="list holders still needing research, then stop")
    ap.add_argument("--only", nargs="*", help="restrict to these tickers")
    ap.add_argument("--out", default="NIFTY50_shareholder_categories")
    a = ap.parse_args()

    index = load_index()
    companies, categories, diag = run(index, only=set(a.only) if a.only else None)

    if a.coverage:
        print(f"{'TICKER':<12} {'HOLDERS':>7} {'PROM':>5} {'PUBLIC':>6} "
              f"{'BASE':>16} {'PROM%':>7}  RECONCILES")
        for c in companies:
            m, rows = c["meta"], c["rows"]
            prom = sum(1 for r in rows if r["category"] == "Promoter")
            base = m.get("shares_scrr")
            d = m.get("drift")
            print(f"{c['ticker']:<12} {len(rows):>7} {prom:>5} {len(rows)-prom:>6} "
                  f"{(f'{base:,}' if base else '-'):>16} "
                  f"{(m.get('promoter_pct') or 0):>7} "
                  f" {m.get('reconciliation')}"
                  f"{'' if d is None else f' ({d:+.1%})'}")
        missing = diag["missing"]
        print(f"\nwith data: {len(companies)}/50   no register yet: {len(missing)}")
        if missing:
            print("  " + ", ".join(missing))
        raise SystemExit(0)

    if a.unresolved:
        pend = unresolved(companies)
        print(f"{len(pend)} distinct names need research\n")
        for name, info in pend.items():
            print(f"{info['shares']:>15,}  {name}   [{', '.join(info['tickers'][:6])}]")
        raise SystemExit(0)

    out = ROOT / "output" / f"{a.out}.xlsx"
    write_workbook(companies, categories, out, index_name=index["index"])
    write_flat(companies, ROOT / "output" / f"{a.out}.csv")
    (ROOT / "output" / f"{a.out}.json").write_text(json.dumps(companies, indent=2))

    rows = [r for c in companies for r in c["rows"]]
    print(f"companies: {len(companies)}   holder rows: {len(rows)}")
    for cat, n in Counter(r["category"] for r in rows).most_common():
        print(f"   {str(cat):<24} {n}")
    print(f"needs review: {sum(1 for r in rows if r.get('needs_review'))}")
    if diag["missing"]:
        print(f"no register yet: {', '.join(diag['missing'])}")
    for w in diag["warnings"]:
        print("WARN", w)
    print("wrote", out)
