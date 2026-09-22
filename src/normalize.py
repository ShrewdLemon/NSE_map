"""Name normalisation shared by the rule engine and the entity master."""
import re

# Bloomberg suffixes that carry no identifying information.
_NOISE = r"""
    \b(?:ltd|limited|pvt|private|plc|inc|incorporated|llc|llp|lp|corp|corporation|
    co|company|holdings?|group|the|sa|ag|nv|se|as|ab|oyj|spa|pte|gmbh)\b
"""
_NOISE_RE = re.compile(_NOISE, re.IGNORECASE | re.VERBOSE)


def normalize(name: str) -> str:
    """Collapse a holder name to a stable lookup key.

    'ICICI Prudential Asset Management Co Ltd/India' -> 'icici prudential asset management'
    """
    s = name.lower().replace("\xa0", " ")
    s = s.split("/")[0]          # drop Bloomberg's /India, /The disambiguators
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _NOISE_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def name_tokens(name: str) -> set:
    return set(normalize(name).split())
