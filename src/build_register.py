"""Turn a filed shareholding pattern into a holder register the pipeline can read.

One JSON per company under data/registers/<TICKER>.json describes what the
filing says. This module turns that into the two files build.py consumes:

    output/holders_raw_<TICKER>.json   the holder rows
    data/promoters_<TICKER>.json       the promoter overlay registry

Generalises src/build_reliance_register.py, where the same logic was hand
written for a single company.
"""
import json
import re
from pathlib import Path

from promoters import _person_like

ROOT = Path(__file__).resolve().parent.parent
REGISTERS = ROOT / "data" / "registers"

# Indian filings quote percentages on the SCRR basis (A)+(B)+(C2), which
# excludes shares underlying depository receipts. A source that hands back the
# grand total instead inflates every converted share count - for Reliance by
# about 1.8%. Holders that publish both a count and a percentage pin the real
# denominator down, so we recover it from them rather than trusting the header.
DENOMINATOR_TOLERANCE = 0.005   # 0.5%; wider than rounding, narrower than a DR gap
MIN_PAIRS_TO_OVERRIDE = 3       # one stale row should not move the denominator

# Filing classes that describe a natural person rather than an entity.
_PERSON_CLASS = re.compile(r"individual|huf|director|relative|promoter\s*-\s*person", re.I)


def implied_denominator(holders):
    """Median total implied by holders publishing both a share count and a %."""
    implied = sorted(
        h["shares"] / (h["pct"] / 100)
        for h in holders
        if h.get("shares") and h.get("pct")
    )
    if not implied:
        return None, 0
    return implied[len(implied) // 2], len(implied)


def resolve_denominator(reg):
    """Return (shares_scrr, note). Prefers the figure the holders actually imply."""
    stated = reg.get("shares_scrr")
    pairs = [h for h in reg.get("promoter_group", []) if h.get("shares") and h.get("pct")]
    pairs += [h for h in reg.get("public_holders", []) if h.get("shares") and h.get("pct")]
    # promoter_group uses shares_filed; normalise before measuring.
    probe = [{"shares": h.get("shares") or h.get("shares_filed"), "pct": h.get("pct")}
             for h in reg.get("promoter_group", []) + reg.get("public_holders", [])]
    probe = [h for h in probe if h["shares"] and h.get("pct")]
    implied, n = implied_denominator(probe)

    if implied is None:
        return stated, "no holder published both a count and a percentage"
    if not stated:
        return round(implied), f"denominator recovered from {n} count/percentage pairs"
    drift = abs(implied - stated) / stated
    if drift <= DENOMINATOR_TOLERANCE:
        return stated, f"stated denominator agrees with {n} holders to {drift:.3%}"
    if n >= MIN_PAIRS_TO_OVERRIDE:
        return (round(implied),
                f"stated {stated:,} disagreed with {n} holders by {drift:.2%}; "
                f"used the implied {round(implied):,} (SCRR basis)")
    return stated, f"stated denominator kept; only {n} pair(s) disagreed by {drift:.2%}"


# Below this a filed percentage is too coarse to check a share count against:
# a holding rounded to 0.00% implies zero shares, which is not what it means.
_PCT_FLOOR = 0.01
_COUNT_TOLERANCE = 0.05


def reconcile_count(shares, pct, total):
    """Returns (count, note, doubtful) for one holding.

    Both fields can be wrong, and differently. SBI Life came back with
    Government of Singapore holding 2,134,450,960 shares against a base of
    1,002,568,002 - 212% of the company, so the count is impossible and the
    percentage beside it is right. In the same filing SBI Mutual Fund's count
    is plausible and its percentage looks like 12.13 with a digit dropped.

    So only the impossible is overridden: a holding cannot exceed the share
    base. Where the two merely disagree the filed count stands and the row is
    flagged, because picking a winner would be inventing data.

    The tolerance scales with the rounding in the percentage itself. A holding
    filed as 0.02% carries half a basis point of slack, which is 25% of the
    figure - HCLTech's Kiran Nadar, filed at 494,602 shares and 0.018%, is
    within that and must not be "corrected" to the rounder number.
    """
    if not total:
        return shares, None, False

    if shares and shares > total:
        if pct and pct >= _PCT_FLOOR:
            implied = round(pct / 100 * total)
            return implied, (f"count {shares:,} exceeds the {total:,.0f} share "
                             f"base; used {pct}% ({implied:,})"), True
        return None, (f"count {shares:,} exceeds the {total:,.0f} share base "
                      f"and no percentage to fall back on; dropped"), True

    if pct is None or pct < _PCT_FLOOR:
        return shares, None, False
    implied = round(pct / 100 * total)
    if not implied:
        return shares, None, False
    if shares is None:
        return implied, None, False

    slack = max(_COUNT_TOLERANCE, 0.005 / pct)
    if abs(shares - implied) / implied > slack:
        return shares, (f"count {shares:,} and {pct}% disagree "
                        f"({implied:,}); kept the count"), True
    return shares, None, False


def _is_individual(name, holder_class):
    if holder_class and _PERSON_CLASS.search(holder_class):
        # 'Bodies Corporate' never matches; 'Individuals/HUF' does.
        return True
    if holder_class:
        return False
    return _person_like(name)


def _shares(entry, total, key="shares"):
    """Filed count where stated, else converted from the percentage.

    A filed zero is a fact - a promoter group member listed as holding nil -
    so it is kept as 0 rather than collapsed into "no figure".
    """
    if entry.get(key) is not None:
        return int(entry[key])
    if entry.get("pct") is not None and total:
        return round(entry["pct"] / 100 * total)
    return None


def reconciliation(promoter_shares, promoter_pct, total):
    """How well the parsed promoter rows agree with the filed headline figure.

    Fifty filings mean fifty layouts, and a parse that silently drops rows is
    worse than one that admits it. The filed promoter percentage is an
    independent check on the rows: if they reconcile, the promoter side is
    trustworthy; if they do not, the register says so rather than presenting a
    partial table as complete.
    """
    if not (promoter_pct and total):
        return "unchecked", None
    expected = promoter_pct / 100 * total
    if not expected:
        return "unchecked", None
    drift = (promoter_shares - expected) / expected
    if abs(drift) <= 0.01:
        return "reconciled", drift
    if abs(drift) <= 0.10:
        return "close", drift
    return "unreconciled", drift


def build(ticker, quarter_label=None):
    reg = json.loads((REGISTERS / f"{ticker}.json").read_text())
    total, denom_note = resolve_denominator(reg)
    quarters = reg.get("quarters") or [quarter_label or reg["as_of_label"]]
    latest = quarters[-1]

    holders, promoter_group = [], []
    seen, corrections = set(), []

    for p in reg.get("promoter_group", []):
        shares = _shares(p, total, "shares_filed")
        shares, note, doubt = reconcile_count(shares, p.get("pct"), total)
        if note:
            corrections.append(f"{ticker}/{p['filed_name']}: {note}")
        promoter_group.append({
            "filed_name": p["filed_name"],
            "shares_filed": shares or 0,
            "class": p.get("holder_class"),
        })
        key = p["filed_name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        holders.append({
            "holder_name": p["filed_name"],
            "bloomberg_holder_type": (
                "Individual" if _is_individual(p["filed_name"], p.get("holder_class"))
                else "Institution"),
            "quarters": {q: (shares if q == latest else None) for q in quarters},
            "filed_class": p.get("holder_class"),
            "doubtful": doubt,
        })

    for h in reg.get("public_holders", []):
        key = h["holder_name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        series = h.get("pct_series") or {}
        qmap = {}
        for q in quarters:
            if q == latest and h.get("shares") is not None:
                # A count the filing states beats the same count re-derived
                # from a rounded percentage.
                qmap[q] = int(h["shares"])
            elif series.get(q) is not None and total:
                qmap[q] = round(series[q] / 100 * total)
            elif q == latest:
                qmap[q] = _shares(h, total)
            else:
                qmap[q] = None
        fixed, note, doubt = reconcile_count(qmap.get(latest), h.get("pct"), total)
        if note:
            corrections.append(f"{ticker}/{h['holder_name']}: {note}")
            qmap[latest] = fixed
        holders.append({
            "holder_name": h["holder_name"],
            "bloomberg_holder_type": (
                "Individual" if _is_individual(h["holder_name"], h.get("holder_class"))
                else "Institution"),
            "quarters": qmap,
            "filed_class": h.get("holder_class"),
            "doubtful": doubt,
        })

    raw = {
        "company": reg["company"],
        "ticker": ticker,
        "isin": reg.get("isin"),
        "as_of": reg.get("as_of"),
        "shares_scrr": total,
        "denominator_note": denom_note,
        "quarter_labels": quarters,
        "holders": holders,
        "source_urls": reg.get("source_urls", []),
        "notes": reg.get("notes"),
        "corrections": corrections,
    }
    promoter_shares = sum(p["shares_filed"] for p in promoter_group)
    status, drift = reconciliation(promoter_shares, reg.get("promoter_pct"), total)
    raw["promoter_reconciliation"] = status
    raw["promoter_drift"] = drift
    raw["promoter_pct_filed"] = reg.get("promoter_pct")

    registry = {
        "company": reg["company"],
        "isin": reg.get("isin"),
        "source": (f"SEBI LODR Reg 31 shareholding pattern (Table II - Promoter & "
                   f"Promoter Group), as at {reg.get('as_of')}"),
        "source_urls": reg.get("source_urls", []),
        "as_of": reg.get("as_of"),
        "promoter_total_pct": reg.get("promoter_pct"),
        "promoter_total_shares_filed": sum(p["shares_filed"] for p in promoter_group),
        # Register and registry are cut from the same filing here, so the
        # numeric matcher confirms arithmetic rather than corroborating an
        # independent source. Only a separate register (a Bloomberg OWN export,
        # say) makes the two matchers genuinely independent.
        "bonus_adjustment_note": reg.get(
            "bonus_note",
            "Holder counts and filed counts come from the same filing, so the "
            "bonus factor is 1."),
        "bonus_factor": reg.get("bonus_factor", 1),
        "promoter_group": promoter_group,
    }

    (ROOT / "output").mkdir(exist_ok=True)
    out_raw = ROOT / "output" / f"holders_raw_{ticker}.json"
    out_reg = ROOT / "data" / f"promoters_{ticker}.json"
    out_raw.write_text(json.dumps(raw, indent=2))
    out_reg.write_text(json.dumps(registry, indent=2))
    return raw, registry


# Indian ISINs are INE/INF/INA followed by nine alphanumerics. A malformed one
# is worth flagging: it usually means the whole record came from a weak source.
_ISIN = re.compile(r"^IN[EFA][0-9A-Z]{9}$")


def check(raw, registry):
    """Arithmetic sanity checks. Returns a list of human-readable warnings."""
    warn = []
    total = raw["shares_scrr"]
    tick = raw["ticker"]

    if not total:
        warn.append(f"{tick}: no share base, so percentages cannot be converted")
    if raw.get("isin") and not _ISIN.match(raw["isin"].strip().upper()):
        warn.append(f"{tick}: ISIN {raw['isin']!r} is not a well-formed Indian ISIN")
    if not raw.get("quarter_labels"):
        warn.append(f"{tick}: no quarter label")
    pct = registry.get("promoter_total_pct")
    if pct is not None and not 0 <= pct <= 100:
        warn.append(f"{tick}: promoter_pct {pct} is outside 0-100")
    negatives = [h["holder_name"] for h in raw["holders"]
                 if any((v or 0) < 0 for v in h["quarters"].values())]
    if negatives:
        warn.append(f"{tick}: negative holding for {', '.join(negatives[:3])}")
    if len(raw["holders"]) < 3:
        warn.append(f"{tick}: only {len(raw['holders'])} holder(s) - source looks thin")
    filed = registry["promoter_total_shares_filed"]
    if total and pct:
        expected = pct / 100 * total
        if expected and abs(filed - expected) / expected > 0.01:
            warn.append(
                f"{tick}: promoter members sum to {filed:,} but "
                f"{pct}% of {total:,} is {expected:,.0f} "
                f"({(filed - expected) / expected:+.2%})")
    if total:
        held = sum(v for h in raw["holders"] for v in [h["quarters"].get(
            raw["quarter_labels"][-1])] if v)
        if held > total * 1.001:
            warn.append(f"{tick}: named holders exceed the share base "
                        f"({held:,} of {total:,.0f})")
    warn += raw.get("corrections", [])
    return warn


if __name__ == "__main__":
    import sys
    for t in sys.argv[1:]:
        raw, registry = build(t)
        print(f"{t}: {len(raw['holders'])} holders, "
              f"{len(registry['promoter_group'])} promoter members, "
              f"base {raw['shares_scrr']:,}")
        print("   ", raw["denominator_note"])
        for w in check(raw, registry):
            print("    WARN", w)
