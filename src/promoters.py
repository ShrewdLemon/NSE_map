"""Promoter overlay: match filed Table II names onto Bloomberg holder rows.

Two independent matchers run over every row and must agree:
  * token   - normalised name token-set containment (handles surname reordering)
  * numeric - a quarter's share count equals the filed count x bonus_factor,
              including individual+HUF combinations that Bloomberg merges

Disagreement is surfaced rather than silently resolved.
"""
import itertools
import re

from normalize import normalize

DEFAULT_BONUS_FACTOR = 1  # registries override; see 'bonus_factor' in the registry


# Words that mark a name as an entity rather than a natural person.
_CORPORATE = re.compile(
    r"\b(ltd|limited|pvt|private|llp|plc|inc|llc|lp|corp|co|company|trust|"
    r"services|securities|capital|property|properties|financial|finance|"
    r"insurance|brokers|holdings?|industries|investments?|fund|bank|it)\b",
    re.IGNORECASE,
)


def _tokens(name: str) -> frozenset:
    return frozenset(t for t in normalize(name).split() if t != "huf")


def _person_like(name: str) -> bool:
    """A natural person's name carries no corporate marker."""
    return not _CORPORATE.search(name)


def _token_match(a: str, b: str) -> bool:
    """Exact token-set equality, or subset only between two personal names.

    Subset across the person/entity boundary would let 'Anand Rathi' match
    'Anand Rathi Financial Services Ltd', so it is restricted to people, where
    a filing may carry a middle name the register omits.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if _person_like(a) and _person_like(b):
        return ta <= tb or tb <= ta
    return False


def _numeric_targets(promoter_group, factor):
    """filed x factor for each promoter, plus merged individual+HUF sums."""
    targets = {}
    for p in promoter_group:
        targets.setdefault(p["shares_filed"] * factor, []).append(p["filed_name"])

    hufs = [p for p in promoter_group if "huf" in p["filed_name"].lower()]
    plain = [p for p in promoter_group if "huf" not in p["filed_name"].lower()]
    for huf, ind in itertools.product(hufs, plain):
        # Only merge when the HUF shares a surname with the individual.
        if not (_tokens(huf["filed_name"]) & _tokens(ind["filed_name"])):
            continue
        total = (huf["shares_filed"] + ind["shares_filed"]) * factor
        targets.setdefault(total, []).append(
            f"{ind['filed_name']} + {huf['filed_name']}"
        )
    return targets


def match(holders, registry):
    """Annotate each holder with promoter evidence. Returns (results, issues)."""
    group = registry["promoter_group"]
    factor = registry.get("bonus_factor", DEFAULT_BONUS_FACTOR)
    numeric = _numeric_targets(group, factor)
    filed_names = [p["filed_name"] for p in group]

    results, issues = {}, []
    for h in holders:
        token_hit = [
            fn for fn in filed_names if _token_match(h["holder_name"], fn)
        ]

        numeric_hit, matched_qtr = [], None
        for qtr, val in h["quarters"].items():
            # A zero holding is not evidence: many holders sit at zero.
            if val and val in numeric:
                numeric_hit, matched_qtr = numeric[val], qtr
                break

        is_promoter = bool(token_hit or numeric_hit)
        if is_promoter:
            results[h["holder_name"]] = {
                "filed_names": sorted(set(token_hit) | set(numeric_hit)),
                "matched_by": (
                    "token+numeric" if token_hit and numeric_hit
                    else "token" if token_hit else "numeric"
                ),
                "numeric_quarter": matched_qtr,
            }
            # A holder sitting at zero across every quarter cannot be matched
            # numerically, so token-only is the expected result, not a conflict.
            holds_nothing = not any(h["quarters"].values())
            if bool(token_hit) != bool(numeric_hit) and not holds_nothing:
                issues.append(
                    f"{h['holder_name']}: matched by "
                    f"{'token only' if token_hit else 'numeric only'} "
                    f"-> {token_hit or numeric_hit}"
                )
    return results, issues
