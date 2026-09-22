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
    "jio", "invesco asset management india", "bank of india",
    "max life", "aditya", "mirae asset", "parag parikh", "ppfas", "cpse",
    "nippon", "baroda bnp", "sundaram", "whiteoak", "360 one", "helios capital",
    "old bridge", "jm financial", "lici", "lic mf", "life insurance corporation",
    "new india assurance", "general insurance corporation", "gic housing",
    "trust mutual fund", "trust amc", "franklin india", "hsbc mutual fund",
)
# 'trust' alone was in this list and had to come out: it is a legal form, not
# evidence of Indian incorporation, and it silently made every foreign entity
# organised as a trust - FlexShares Trust, for one - read as domestic.

# An Indian fund house names each scheme after itself, so a scheme name is the
# house name plus a product word. Matching the pair is what lets 'SBI Nifty 50
# ETF' and 'Kotak Arbitrage Fund' resolve without a web call.
_SCHEME = re.compile(
    r"\b(funds?|etfs?|exchange traded|schemes?|plan|index fund|"
    r"advantage|arbitrage|flexi ?cap|multi ?cap|large ?cap|mid ?cap|small ?cap|"
    r"bluechip|balanced|equity|hybrid|savings|opportunities)\b", re.I)

# Insurers run unit-linked and pension funds whose names end in 'Fund'. They
# are insurance float, not an asset manager's pooled money, so they have to be
# recognised before the scheme rule claims them.
_INSURER_SCHEME = re.compile(
    r"^\s*(?:lic[i]?\b|life insurance corp|sbi life|hdfc life|icici pru(?:dential)? life|"
    r"max life|bajaj allianz life|kotak (?:mahindra )?life|tata aia)", re.I)

# Retirement money under the national pension system.
_PENSION = re.compile(r"\b(nps trust|national pension system|epfo|"
                      r"employees provident fund|pension fund manager)\b", re.I)

# The Indian state holds listed equity under a handful of fixed legal names.
# Each is decisive on its face: no private entity is called 'President of India'.
# For a public sector undertaking these appear in Table II and the promoter
# overlay catches them first; this rule is for the rest, above all SUUTI, which
# holds public stakes in companies it never promoted.
_INDIAN_STATE = re.compile(
    r"^(?:the\s+)?(?:president of india|government of india|"
    r"governor of [a-z ]+|union of india|"
    r"(?:administrator of the )?specified undertaking of the unit trust of india"
    r"(?: ?- ?suuti)?|suuti)$", re.I)

_AMC = re.compile(
    r"\b(asset manage\w*|amc|mutual funds?|money manage\w*|"
    r"funds? advisors?|funds? manage\w*|investment manage\w*|investment mgmt)\b", re.I
)
_INSURANCE = re.compile(
    r"\b(life insurance|insurance co\w*|assurance|life)\b.*\b(ltd|limited|co\w*)\b", re.I)
_INSURANCE_SIMPLE = re.compile(r"\binsurance\b", re.I)
_BANK = re.compile(r"\b(bank|banca|banque|bancorp)\b", re.I)


def domicile(normalised: str) -> str | None:
    """'IN' when the name itself proves Indian incorporation, else None."""
    if "india" in normalised or "indian" in normalised:
        return "IN"
    # 'X Mutual Fund' is SEBI terminology: a mutual fund so named is a
    # SEBI-registered Indian scheme by definition. Foreign managers appear
    # under a group or asset-management name instead.
    if normalised.endswith("mutual fund") or normalised.endswith("mutual funds"):
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

    if _INDIAN_STATE.match(holder_name.strip()) or _INDIAN_STATE.match(normalised):
        return "Government", "high", "rule:indian-state-entity"

    # An insurance BROKER is not an insurer - check before the insurer rule.
    if "insurance broker" in normalised:
        return None

    # Retirement money first: 'NPS Trust' carries no house name and would
    # otherwise fall through to research on every company it appears in.
    if _PENSION.search(holder_name):
        return "Domestic Pension Fund", "high", "rule:indian-pension-scheme"

    # An insurer's unit-linked fund is insurance float, not managed client
    # money, so this must run before the scheme rule.
    if _INSURER_SCHEME.search(holder_name) and dom == "IN":
        return "Domestic Insurance", "high", "rule:indian-insurer-scheme"

    # 'X Trustee Company Limited' is the trustee of X Mutual Fund - a fund
    # house vehicle, however little the name looks like one.
    if dom == "IN" and re.search(r"\btrustee\b", holder_name, re.I):
        return "Domestic AMC", "high", "rule:indian-fund-trustee"

    # An Indian house's scheme: house name plus a product word.
    if dom == "IN" and _SCHEME.search(holder_name):
        return "Domestic AMC", "high", "rule:indian-fund-scheme"

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
