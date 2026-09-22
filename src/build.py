"""Build the classified shareholder register.

  parse -> promoter overlay -> deterministic rules -> entity master -> category

Anything the three passes cannot settle is emitted with needs_review set rather
than guessed, so the reviewer sees exactly what is unresolved.
"""
import argparse
import csv
import json
from pathlib import Path

import entity_master as em
import rules
from categorize import categorize
from normalize import normalize
from promoters import match as match_promoters
from write_output import write as write_xlsx

ROOT = Path(__file__).resolve().parent.parent

# Inverse of the decision table, for caching what the rules settle.
_TYPE_FOR_CATEGORY = {
    "Domestic AMC": "asset_manager", "Foreign AMC": "asset_manager",
    "Domestic Insurance": "insurer", "Foreign Insurance": "insurer",
}
_VEHICLE_FOR_CATEGORY = {
    "Domestic AMC": "managed_funds", "Foreign AMC": "managed_funds",
    "Domestic Insurance": "insurance_float", "Foreign Insurance": "insurance_float",
}


def build(holders_path, registry_path, ticker, out_stem):
    data = json.loads(Path(holders_path).read_text())
    holders, quarters = data["holders"], data["quarter_labels"]
    registry = json.loads(Path(registry_path).read_text())
    promoters, promoter_issues = match_promoters(holders, registry)
    master = em.load()

    rows = []
    for h in holders:
        name = h["holder_name"]
        btype = h["bloomberg_holder_type"]
        row = {
            "holder_name": name, "quarters": h["quarters"],
            "bloomberg_holder_type": btype, "needs_review": False,
        }

        if name in promoters:
            cat, why = categorize(is_promoter=True, bloomberg_type=btype, country="IN",
                                  entity_type=None, holding_vehicle=None)
            ev = promoters[name]
            row.update(category=cat, basis=f"filing ({ev['matched_by']})",
                       confidence="high", country="IN", reason=why,
                       source=registry["source"],
                       filed_as="; ".join(ev["filed_names"]))
            rows.append(row); continue

        rec = em.get(master, name)
        if rec:
            cat, why = categorize(is_promoter=False, bloomberg_type=btype,
                                  country=rec["country"], entity_type=rec["entity_type"],
                                  holding_vehicle=rec["holding_vehicle"])
            row.update(category=cat, basis=rec["basis"], confidence=rec["confidence"],
                       country=rec["country"], entity_type=rec["entity_type"],
                       holding_vehicle=rec["holding_vehicle"], reason=why,
                       source=rec.get("source") or rec.get("evidence"),
                       needs_review=rec["confidence"] == "low" or cat is None)
            rows.append(row); continue

        r = rules.classify(name, normalize(name), btype)
        if r:
            cat, conf, basis = r
            row.update(category=cat, basis=basis, confidence=conf,
                       country="IN" if "Domestic" in cat else None,
                       reason="name-based rule", source="deterministic rule")
            # Individuals are people, not entities - nothing worth caching.
            if btype != "Individual":
                em.upsert(master, name,
                          country="IN" if "Domestic" in cat else None,
                          entity_type=_TYPE_FOR_CATEGORY.get(cat),
                          holding_vehicle=_VEHICLE_FOR_CATEGORY.get(cat),
                          confidence=conf, basis=basis,
                          evidence="matched by deterministic name rule",
                          ticker=ticker)
        else:
            row.update(category=None, basis="unresolved", confidence="low",
                       reason="no filing match, no cached entity, no rule",
                       needs_review=True)
        rows.append(row)

    out_xlsx = ROOT / "output" / f"{out_stem}.xlsx"
    write_xlsx(rows, quarters, data["company"], out_xlsx)

    with open(ROOT / "output" / f"{out_stem}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Company name", "Share holder name", "Share holder category"]
                   + [f"{q} No of shares" for q in quarters]
                   + ["Basis", "Confidence", "Country", "Entity type",
                      "Holding vehicle", "Review?", "Source"])
        for r in rows:
            w.writerow([data["company"], r["holder_name"], r["category"]]
                       + [r["quarters"].get(q) for q in quarters]
                       + [r.get("basis"), r.get("confidence"), r.get("country"),
                          r.get("entity_type"), r.get("holding_vehicle"),
                          "REVIEW" if r["needs_review"] else "", r.get("source")])

    (ROOT / "output" / f"{out_stem}.json").write_text(json.dumps(rows, indent=2))
    em.save(master)
    return rows, promoter_issues


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--holders", default=str(ROOT / "output" / "holders_raw.json"))
    ap.add_argument("--registry", default=str(ROOT / "data" / "promoters_ANANDRATHI.json"))
    ap.add_argument("--ticker", default="ANANDRATHI")
    ap.add_argument("--out", default="ANANDRATHI_shareholder_categories")
    a = ap.parse_args()

    rows, issues = build(a.holders, a.registry, a.ticker, a.out)
    from collections import Counter
    print(f"rows: {len(rows)}")
    for cat, n in Counter(r["category"] for r in rows).most_common():
        print(f"   {str(cat):<24} {n}")
    pending = [r['holder_name'] for r in rows if r['needs_review']]
    print(f"needs review: {len(pending)}")
    if issues:
        print("promoter matcher disagreements:", issues)
