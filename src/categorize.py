"""Collapse (promoter status, domicile, entity type, holding vehicle) into one
Book1 category.

Order matters. Promoter is an overlay taken from the company's filed
shareholding pattern and wins over everything else; after that the holding
vehicle decides for banking groups, because the taxonomy has a single
domicile-neutral 'Bank' bucket and a group's stake may sit with its asset
manager rather than on its own book.
"""

# For a BANKING GROUP only, the vehicle holding the stake decides the category.
# The taxonomy's 'Bank' bucket has no domestic/foreign split, so a group whose
# stake sits with its asset-management arm is better described as an AMC. This
# does NOT generalise: applying it to every holder would empty the Insurance
# buckets (most insurers run an investment arm) and would turn a private family
# trust into an AMC.
_BANK_VEHICLE = {
    "managed_funds": "AMC",
    "insurance_float": "Insurance",
    "pension_assets": "Pension Fund",
    "sovereign_assets": "Government",
}

_TYPE_FALLBACK = {
    "asset_manager": "AMC",
    "exchange_traded_fund_trust": "AMC",
    "insurer": "Insurance",
    "pension_fund": "Pension Fund",
    "sovereign_wealth_fund": "Government",
    "bank": "Bank",
    "operating_company": "corporate",
    "private_family_trust": "corporate",
    "broker": "corporate",
    "other": "corporate",
}


def categorize(*, is_promoter, bloomberg_type, country, entity_type, holding_vehicle):
    """Returns (category, reason). country is ISO alpha-2 or None."""
    if is_promoter:
        return "Promoter", "in filed promoter & promoter group"

    if bloomberg_type == "Individual":
        return "Individual", "natural person, not in promoter group"

    domestic = (country or "").upper() == "IN"
    prefix = "Domestic" if domestic else "Foreign"

    # Banking groups: the vehicle decides, per the agreed ruling.
    if entity_type == "bank":
        stem = _BANK_VEHICLE.get(holding_vehicle)
        if stem in ("AMC", "Insurance", "Pension Fund"):
            return f"{prefix} {stem}", f"banking group holding via {holding_vehicle}"
        return "Bank", f"banking group holding via {holding_vehicle or 'own book'}"

    # Everyone else is classified by what the entity is.
    stem = _TYPE_FALLBACK.get(entity_type)
    if stem is None:
        return None, f"unmapped entity_type={entity_type!r}"

    if stem == "Bank":
        return "Bank", "bank, domicile-neutral bucket"
    if stem == "Government":
        return ("Government" if domestic else "Foreign Government"), "sovereign/state capital"
    if stem == "corporate":
        return f"{prefix} corporate", f"{entity_type} treated as a corporate holder"
    return f"{prefix} {stem}", f"{entity_type} holding via {holding_vehicle}"
