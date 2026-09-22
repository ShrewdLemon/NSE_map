"""Compare an independent ownership reading against a built register.

The detailed extraction and this cross-check read different sources, so where
they agree on a promoter percentage that is real corroboration. Where they
disagree the register is not silently rewritten - the disagreement is reported,
because only one of them is wrong and the filing decides which.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTERS = ROOT / "data" / "registers"

PCT_TOLERANCE = 0.5      # percentage points; wider than rounding in either source
SHARE_TOLERANCE = 0.01   # 1% on the share base


def compare(record, register):
    """Returns a list of disagreements between the two readings."""
    out, t = [], register["ticker"]

    a, b = register.get("promoter_pct"), record.get("promoter_pct")
    if a is not None and b is not None and abs(a - b) > PCT_TOLERANCE:
        out.append(f"{t}: promoter {a}% filed vs {b}% cross-checked "
                   f"({a - b:+.2f} pts)")

    a, b = register.get("shares_scrr"), record.get("total_shares_scrr")
    if a and b and abs(a - b) / a > SHARE_TOLERANCE:
        out.append(f"{t}: share base {a:,.0f} filed vs {b:,.0f} cross-checked "
                   f"({(a - b) / a:+.2%})")

    qa, qb = register.get("as_of"), (record.get("quarter_end") or "")[:10]
    if qa and qb and qa != qb:
        out.append(f"{t}: quarter {qa} filed vs {qb} cross-checked")
    return out


def supplement(record, register):
    """Add cross-check holders the register is missing. Returns how many."""
    known = {h["holder_name"].strip().lower() for h in register["public_holders"]}
    known |= {p["filed_name"].strip().lower() for p in register["promoter_group"]}
    added = 0
    for h in record.get("top_holders") or []:
        name = (h.get("holder_name") or "").strip()
        if not name or name.lower() in known or h.get("pct") in (None, 0):
            continue
        register["public_holders"].append({
            "holder_name": name,
            "shares": None,
            "pct": h["pct"],
            "holder_class": h.get("holder_class"),
            "provenance": "cross-check reading, not the filed table",
        })
        known.add(name.lower())
        added += 1
    return added


def apply(records, merge_missing=True):
    """Compare every cross-check record to its register. Returns (issues, added)."""
    issues, added = [], {}
    for rec in records:
        t = (rec.get("ticker") or "").strip()
        path = REGISTERS / f"{t}.json"
        if not path.exists():
            issues.append(f"{t}: cross-checked but no register built")
            continue
        reg = json.loads(path.read_text())
        issues += compare(rec, reg)
        if merge_missing:
            n = supplement(rec, reg)
            if n:
                added[t] = n
                path.write_text(json.dumps(reg, indent=2))
    return issues, added
