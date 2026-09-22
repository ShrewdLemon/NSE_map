"""Deterministic first pass. Returns (category, confidence, basis) or None.

Only fires where the name itself is decisive. Anything needing knowledge of the
entity beyond its name falls through to the entity master / web verification.
"""
import re

# Entities incorporated in India. Matched against the normalised name.
_INDIA_MARKERS = (
    "sbi", "icici", "hdfc", "kotak", "axis", "tata", "birla", "nippon india",
    "canara", "dsp", "motilal", "edelweiss", "bandhan", "union", "quant",
    "groww", "zerodha", "uti", "shriram", "navi", "samco", "capitalmind",
    "alphagrep", "angel one", "bajaj", "pnb", "indusind", "star union",
    "jio", "invesco asset management india", "bank of india", "trust",
    "max life", "aditya", "mirae asset investment managers",
)

_AMC = re.compile(
    r"\b(asset manage\w*|amc|mutual funds?|money manage\w*|"
    r"funds? advisors?|funds? manage\w*|investment manage\w*|investment mgmt)\b", re.I
)
_INSURANCE = re.compile(r"\b(life insurance|insurance co|assurance|life)\b.*\b(ltd|co)\b", re.I)
_INSURANCE_SIMPLE = re.compile(r"\binsurance\b", re.I)
_BANK = re.compile(r"\b(bank|banca|banque|bancorp)\b", re.I)


def domicile(normalised: str) -> str | None:
    """'IN' when the name itself proves Indian incorporation, else None."""
    if "india" in normalised or "indian" in normalised:
        return "IN"
    # 'X Mutual Fund' is SEBI terminology: a mutual fund so named is a
    # SEBI-registered Indian scheme by definition. Foreign managers appear
    # under a group or asset-management name instead.
    if normalised.endswith("mutual fund"):
        return "IN"
    for marker in _INDIA_MARKERS:
        if marker in normalised:
            return "IN"
    return None


def classify(holder_name: str, normalised: str, bloomberg_type: str | None):
    """Name-only classification. None means 'needs research'."""
    if bloomberg_type == "Individual":
        return "Individual", "high", "bloomberg-holder-type"

    dom = domicile(normalised)

    # An insurance BROKER is not an insurer - check before the insurer rule.
    if "insurance broker" in normalised:
        return None

    if _AMC.search(holder_name) or "mutual fund" in normalised:
        if dom == "IN":
            return "Domestic AMC", "high", "rule:amc+india"
        return None  # foreign AMC vs bank-owned vehicle needs verification

    if _INSURANCE.search(holder_name) or (
        _INSURANCE_SIMPLE.search(holder_name) and not _BANK.search(holder_name)
    ):
        if dom == "IN":
            return "Domestic Insurance", "high", "rule:insurance+india"
        return None

    return None
