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
# holders. Letting one through double-counts a whole category: Bharti Airtel
# came back with 'Mutual Funds (total)' at 12.14% sitting above the named funds
# inside it, which pushed the named holders to 111% of the share base.
#
# A reference can sit on either side of the label - '(A)(1) Sub-Total' and
# 'Sub-Total (A)(1)' are the same row - and a total may be marked by a suffix
# instead: 'Mutual Funds (total)'. Both are stripped before the label itself is
# matched. A reference is a single letter (optionally with a digit, as in the
# SCRR base '(A)+(B)+(C2)'), a roman numeral or a digit, so a real name like
# 'Alpha Holdings (India) Pvt Ltd' is never mistaken for one.
_TABLE_REF = r"(?:[-\s+]*\((?:[A-Za-z]\d?|[ivx]+|\d)\))*"
_TOTAL_WORD = r"(?:sub\s*[\s-]?\s*total|grand\s*total|total|aggregate|combined)"

# The classes a shareholding pattern groups holders under. A row whose whole
# name is one of these is the group's own line, never a shareholder.
_CLASSES = r"""(?:
    promoters?(?:\s*(?:and|&)\s*promoter\s*group)?
  | public(?:\s*shareholding)?
  | non[\s-]?promoter[\s-]?non[\s-]?public
  | institutions?(?:\s*[-–]?\s*(?:domestic|foreign))?
  | non[\s-]?institutions?
  | (?:domestic|foreign)\s*institutional\s*investors?
  | foreign\s*(?:portfolio|institutional)\s*investors?
      (?:\s*[-–,]?\s*(?:category|cat\.?)?\s*[-–]?\s*(?:[ivx]+|[1-3]))?
  | fiis?  | fpis?  | diis?
  | mutual\s*funds?
  | insurance\s*(?:companies|company)
  | alternat(?:e|ive)\s*investment\s*funds?
  | banks?  | financial\s*institutions?(?:\s*/\s*banks?)?
  | nbfcs?(?:\s*registered\s*with\s*rbi)?
  | (?:central|state)\s*government(?:\s*/\s*president\s*of\s*india)?s?
  | bodies\s*corporate
  | (?:resident\s*)?individuals?(?:\s*shareholders?)?(?:\s*holding.*)?
  | huf  | trusts?  | clearing\s*members?
  | foreign\s*nationals?  | non\s*resident\s*indians?  | nris?
  | key\s*managerial\s*personnel  | directors\s*and\s*their\s*relatives
  | employee\s*(?:benefit\s*)?trusts?  | shares\s*held\s*by\s*employee\s*trusts?
  | any\s*other.*  | others?  | overseas\s*(?:corporate\s*)?bodies?
  | qualified\s*institutional\s*buyers?  | investor\s*education.*
  | governments?\(?s?\)?  | (?:foreign|indian|domestic)\s*banks?
  | venture\s*capital\s*funds?  | (?:foreign\s*)?venture\s*capital\s*investors?
  | provident\s*/?\s*pension\s*funds?  | sovereign\s*wealth\s*funds?
  | asset\s*reconstruction\s*companies  | other\s*financial\s*institutions?
  | foreign\s*direct\s*investment  | name\s*of\s*dr\s*holder.*
  | individuals?\s*/\s*hindu\s*undivided\s*family  | hindu\s*undivided\s*family
  | limited\s*liability\s*partnerships?  | escrow\s*account.*
  | independent\s*directors.*  | body\s*corporates?  | corporate\s*bodies?
  | insurance\s*funds?  | mutual\s*funds?\s*/\s*uti  | uti
  | .*nominal\s*share\s*capital.*  | .*in\s*excess\s*of\s*rs.*
  | .*shares\s*underlying\s*(?:depository|dr).*
  | (?:central|state)\s*government\s*/?\s*(?:governor|president).*
  | shareholding\s*by\s*companies.*  | associate\s*companies.*
  | relatives\s*of\s*promoters.*  | trusts?\s*where.*
  | foreign\s*companies  | overseas?e?\s*corporate\s*bodies
  | foreign\s*[-–].*  | non\s*resident\s*indians?\s*\(nris?\)
  | .*not\s*applicable.*  | no\s*promoter.*
  | employee\s*benefit\s*trusts?\s*/?\s*employee\s*welfare\s*trusts?.*
  | .*under\s*sebi\s*\(share\s*based.*
  | bod(?:y|ies)\s*corp\w*\s*[-–]?\s*(?:ltd|limited)?\s*liability\s*partnerships?
  | trusts?\s*\(employees?\)  | employees?\s*trusts?
)"""

_AGGREGATE = re.compile(
    r"^\s*" + _TABLE_REF + r"\s*"
    r"(?:" + _TOTAL_WORD + r"\s*(?:of|for)?\s*)?"      # 'Total Mutual Funds'
    r"(?:" + _CLASSES + r"|" + _TOTAL_WORD + r")"
    r"\s*[-–,]?\s*"
    r"(?:\(?\s*" + _TOTAL_WORD + r"\s*\)?)?"          # 'Mutual Funds (total)'
    # A trailing qualifier such as '(collective)' or '(various schemes)' does
    # not make a category line into a shareholder.
    r"(?:\s*\((?:collective|various[^)]*|aggregate[^)]*|[^)]{0,3})\))?"
    r"\s*" + _TABLE_REF + r"\s*$",
    re.I | re.X)

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


# A SEBI table row is numbered with a parenthesised enumerator: '(a)', '(i)',
# '(1)', "('c)" once PDF extraction has added a stray quote. The enumerator is
# noise rather than proof of a heading - "('2) (a) HCL Technologies Stock
# Options" is a real holder - so it is stripped and the name judged on what
# remains.
_ENUMERATOR = re.compile(r"""^\s*['"]?\s*\(\s*['"]?\s*[A-Za-z0-9]{1,3}\s*\)\s*""")
# Caption text that wrapped out of a table header and into a name buffer.
_CAPTION = re.compile(r"Table\s+[IV]+\s*[-–]|Statement showing|Category of shareholder", re.I)



def _clean_name(raw):
    if not raw:
        return None
    raw = str(raw)
    for _ in range(3):                      # "('2) (a) Name" carries two
        stripped = _ENUMERATOR.sub("", raw)
        if stripped == raw:
            break
        raw = stripped
    if _CAPTION.search(raw):
        return None
    # A holder's name starts with a capital, a digit or a bracket. A fragment
    # of a wrapped sentence ("capital in excess of Rs. 2 lakhs") starts lower.
    if raw[:1].islower():
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
    # Six companies came back with the promoter holding as a fraction - Asian
    # Paints as 0.5263 rather than 52.63 - which then dragged the recovered
    # share base a hundredfold out. A promoter block below 1% is possible but
    # rare; where the named promoters themselves imply percent-scale, the
    # figure is rescaled and the assumption recorded.
    if pct is not None and 0 < pct < 1 and promoters:
        implied = sum((p.get("shares_filed") or 0) for p in promoters)
        base = _num(rec.get("total_shares_scrr"))
        if base and implied and implied / base > 0.01:
            warn.append(f"{ticker}: promoter_pct {pct} read as a fraction; "
                        f"rescaled to {pct * 100:.2f}%")
            pct *= 100
    has_promoter = rec.get("has_promoter")
    if has_promoter is None:
        has_promoter = bool(promoters) or bool(pct)
    if has_promoter and not promoters:
        warn.append(f"{ticker}: promoter_pct {pct} but no promoter names returned")
    if promoters and not pct:
        warn.append(f"{ticker}: promoter names returned but no promoter_pct")

    # The same fraction/percent confusion reaches individual holders: Adani
    # Enterprises' holder percentages implied a base of 130 billion shares for
    # a company with about 1.3 billion. The promoter block gives an anchor -
    # its members' shares over its own percentage - and any holder whose
    # implied base is a hundred times that is rescaled to match.
    anchor = None
    if pct and promoters:
        filed = sum((p.get("shares_filed") or 0) for p in promoters)
        if filed:
            anchor = filed / (pct / 100)
    if anchor:
        rescaled = 0
        for h in promoters:
            if not (h.get("shares_filed") and h.get("pct")):
                continue
            implied = h["shares_filed"] / (h["pct"] / 100)
            if abs(implied - 100 * anchor) / (100 * anchor) < 0.05:
                h["pct"] *= 100
                rescaled += 1
        for h in publics:
            if not (h.get("shares") and h.get("pct")):
                continue
            implied = h["shares"] / (h["pct"] / 100)
            if abs(implied - 100 * anchor) / (100 * anchor) < 0.05:
                h["pct"] *= 100
                rescaled += 1
        if rescaled:
            warn.append(f"{ticker}: {rescaled} holder percentage(s) read as "
                        f"fractions; rescaled against the promoter block")

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
