"""Turn fetched filing documents into registers.

The filings are pulled through the web-extraction tool, which hands back a
PDF as base64 and writes anything large to a file. This module is the other
half: it walks those result files, matches each back to its ticker by URL,
parses the filed tables and writes data/registers/<TICKER>.json.

Keeping the fetch and the parse apart means a re-parse costs nothing - the
documents are already on disk, so a parser fix is re-run against all fifty
companies in seconds rather than re-fetched.
"""
import base64
import json
import re
from datetime import date
from pathlib import Path

import parse_shp_pdf as P
from ingest_nimble import _clean_name, label

ROOT = Path(__file__).resolve().parent.parent
REGISTERS = ROOT / "data" / "registers"
DOCS = ROOT / "data" / "filings"          # cached filing text, by ticker


def harvest(results_dir, url_to_ticker):
    """Copy fetched documents out of the tool-result dump, keyed by ticker."""
    DOCS.mkdir(parents=True, exist_ok=True)
    found = {}
    for f in sorted(Path(results_dir).glob("*.txt"), key=lambda p: p.stat().st_mtime):
        try:
            d = json.loads(f.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        url = d.get("url")
        content = d.get("content")
        if not url or not content:
            continue
        ticker = url_to_ticker.get(url) or url_to_ticker.get(url.rstrip("/"))
        if not ticker:
            continue
        if content.lstrip().startswith("JVBERi"):        # base64 '%PDF'
            raw = base64.b64decode(content)
            text, _ = _pdf_text(raw)
        elif "<" in content[:200] and "xbrl" in url.lower():
            text = content                                # XBRL comes as text
        else:
            text = content
        (DOCS / f"{ticker}.txt").write_text(text)
        found[ticker] = url
    return found


def _pdf_text(raw):
    import io
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(raw))
    return "\n".join((p.extract_text() or "") for p in reader.pages), reader


# An Indian equity ISIN is INE/INF/INA. An 'IN9' code is a different series -
# partly paid shares, typically - so publishing it as the company's ISIN is
# simply wrong. Better to carry nothing than the wrong identifier.
_EQUITY_ISIN = re.compile(r"^IN[EFA][0-9A-Z]{9}$")


def build_register(ticker, company, sector=None, as_of=None, source_url=None,
                   promoter_pct=None, isin=None):
    """Parse a cached filing into the register the pipeline consumes."""
    text = (DOCS / f"{ticker}.txt").read_text()
    parsed = P.parse_text(text, _clean_name)
    base = P.scrr_base(text)

    promoters = [{"filed_name": r["name"], "shares_filed": r["shares"],
                  "pct": r["pct"], "holder_class": None}
                 for r in parsed["promoters"]]

    # A public holder with a nil holding is not a holder: SEBI only names
    # public shareholders above 1%, so a zero there is a category line that
    # slipped the filter, not a shareholder. Promoter group members are the
    # opposite - the filing lists them precisely because membership matters,
    # holding or not - so their zeros are kept.
    public = [{"holder_name": r["name"], "shares": r["shares"], "pct": r["pct"],
               "holder_class": None}
              for r in parsed["public"] + parsed["non_public"] if r["shares"]]

    lab = label(as_of)
    if isin and not _EQUITY_ISIN.match(isin.strip().upper()):
        isin = None
    reg = {
        "ticker": ticker, "company": company, "sector": sector, "isin": isin,
        "as_of": as_of, "as_of_label": lab, "quarters": [lab] if lab else [],
        "shares_scrr": base, "bonus_factor": 1,
        "bonus_note": ("Holder counts come straight from the filed table, so no "
                       "bonus adjustment applies."),
        "promoter_pct": promoter_pct,
        "has_promoter": bool(promoters),
        "promoter_group": promoters,
        "public_holders": public,
        "source_urls": [u for u in [source_url] if u],
        "notes": "Parsed from the filed SEBI Regulation 31 shareholding pattern.",
        "ingested_on": date.today().isoformat(),
    }
    REGISTERS.mkdir(parents=True, exist_ok=True)
    (REGISTERS / f"{ticker}.json").write_text(json.dumps(reg, indent=2))
    return reg
