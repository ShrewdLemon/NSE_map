"""Normalise raw web-agent output into data/registers/<TICKER>.json.

The agent returns one object per company against the schema in the run request.
This module is the airlock: it cleans, filters and validates before anything
reaches the classification pipeline, so a bad row is dropped here rather than
becoming a confident-looking category later.
"""
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTERS = ROOT / "data" / "registers"

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Subtotal and section-heading rows a filing table carries alongside real
# holders. Letting one through would double-count a whole category.
_AGGREGATE = re.compile(
    r"^\s*(?:\(?[a-c]\d?\)?\s*)?(?:sub[\s-]?total|total|grand total|"
    r"promoter(?:s)?(?: (?:and|&) promoter group)?|public(?: shareholding)?|"
    r"non[\s-]?promoter[\s-]?non[\s-]?public|institutions?|non[\s-]?institutions?|"
    r"foreign portfolio investors?|mutual funds?|insurance companies|"
    r"bodies corporate|banks|alternate investment funds|"
    r"individual shareholders?.*|any other.*|others?|nbfcs registered with rbi|"
    r"central government.*|state government.*|shares held by employee trusts?|"
    r"foreign institutional investors?|resident individuals?|"
    r"clearing members?|trusts?|huf|foreign nationals?|"
    r"key managerial personnel|directors and their relatives)\s*$", re.I)

_NOISE_SUFFIX = re.compile(r"\s*[\(\[]\s*(?:nil|nan|n/?a|-{1,2})\s*[\)\]]\s*$", re.I)


def label(iso):
    """'2026-06-30' -> 'Jun/2026'."""
    if not iso:
        return None
    try:
        y, m, _ = str(iso)[:10].split("-")
        return f"{_MONTHS[int(m) - 1]}/{y}"
    except (ValueError, IndexError):
        return None


def _clean_name(raw):
    if not raw:
        return None
    n = _NOISE_SUFFIX.sub("", str(raw).replace("\xa0", " ")).strip(" .,-")
    n = re.sub(r"\s+", " ", n)
    if len(n) < 3 or _AGGREGATE.match(n):
        return None
    # A row that is only digits, punctuation or a percentage is not a name.
    if not re.search(r"[A-Za-z]{3}", n):
        return None
    return n


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[,\s%]", "", str(v))
    try:
        return float(s)
    except ValueError:
        return None


def _dedupe(entries, name_key, share_key):
    """Collapse repeated names, keeping the row that carries the most detail."""
    best = {}
    for e in entries:
        name = _clean_name(e.get(name_key))
        if not name:
            continue
        row = {name_key: name,
               share_key: _num(e.get(share_key)),
               "pct": _num(e.get("pct")),
               "holder_class": (e.get("holder_class") or "").strip() or None}
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        prior = best.get(key)
        if prior is None:
            best[key] = row
            continue
        score = lambda r: (r[share_key] is not None) + (r["pct"] is not None)
        if score(row) > score(prior):
            best[key] = row
    return list(best.values())


def normalise(rec, sector=None):
    """One agent record -> one register dict. Returns (register, warnings)."""
    warn = []
    ticker = (rec.get("ticker") or "").strip()
    if not ticker:
        return None, ["record carried no ticker"]

    as_of = (rec.get("quarter_end") or "")[:10] or None
    lab = label(as_of)
    if not lab:
        warn.append(f"{ticker}: no usable quarter_end ({rec.get('quarter_end')!r})")

    promoters = _dedupe(rec.get("promoter_group") or [], "filed_name", "shares_filed")
    publics = _dedupe(rec.get("public_holders") or [], "holder_name", "shares")

    # A name cannot be both a promoter and a public holder. The filing decides.
    pkeys = {re.sub(r"[^a-z0-9]", "", p["filed_name"].lower()) for p in promoters}
    before = len(publics)
    publics = [h for h in publics
               if re.sub(r"[^a-z0-9]", "", h["holder_name"].lower()) not in pkeys]
    if before != len(publics):
        warn.append(f"{ticker}: dropped {before - len(publics)} public row(s) that "
                    f"duplicate a promoter name")

    pct = _num(rec.get("promoter_pct"))
    has_promoter = rec.get("has_promoter")
    if has_promoter is None:
        has_promoter = bool(promoters) or bool(pct)
    if has_promoter and not promoters:
        warn.append(f"{ticker}: promoter_pct {pct} but no promoter names returned")
    if promoters and not pct:
        warn.append(f"{ticker}: promoter names returned but no promoter_pct")

    reg = {
        "ticker": ticker,
        "company": rec.get("company_name") or ticker,
        "sector": sector,
        "isin": (rec.get("isin") or "").strip() or None,
        "as_of": as_of,
        "as_of_label": lab,
        "quarters": [lab] if lab else [],
        "shares_scrr": _num(rec.get("total_shares_scrr")),
        "bonus_factor": 1,
        "bonus_note": ("Holder counts and filed counts come from the same "
                       "shareholding pattern, so the bonus factor is 1."),
        "promoter_pct": pct,
        "has_promoter": bool(has_promoter),
        "promoter_group": promoters,
        "public_holders": publics,
        "source_urls": [u for u in (rec.get("source_urls") or []) if u],
        "notes": rec.get("extraction_notes"),
        "ingested_on": date.today().isoformat(),
    }
    if not reg["source_urls"]:
        warn.append(f"{ticker}: no source URL returned")
    return reg, warn


def ingest(records, sectors=None, registers_dir=REGISTERS):
    registers_dir.mkdir(parents=True, exist_ok=True)
    sectors = sectors or {}
    written, warnings = [], []
    for rec in records:
        reg, warn = normalise(rec, sectors.get((rec.get("ticker") or "").strip()))
        warnings += warn
        if reg is None:
            continue
        (registers_dir / f"{reg['ticker']}.json").write_text(json.dumps(reg, indent=2))
        written.append(reg["ticker"])
    return written, warnings
