"""Fold Web Search Agent enrichment output into the entity master.

Input is a JSON array of records shaped like the enrichment output schema:
  holder_name, country_of_incorporation, legal_entity_type,
  holding_vehicle, confidence, evidence, source_url
"""
import json
import sys
from pathlib import Path

import entity_master as em

VALID_TYPES = {
    "asset_manager", "insurer", "bank", "pension_fund", "sovereign_wealth_fund",
    "operating_company", "private_family_trust", "broker",
    "exchange_traded_fund_trust", "other",
}
VALID_VEHICLES = {
    "managed_funds", "insurance_float", "pension_assets", "sovereign_assets",
    "own_balance_sheet", "custody_only", "operating_company_treasury",
}


def merge(paths, ticker="ANANDRATHI"):
    master = em.load()
    merged, rejected = 0, []
    for p in paths:
        for rec in json.loads(Path(p).read_text()):
            name = rec.get("holder_name")
            et = rec.get("legal_entity_type")
            hv = rec.get("holding_vehicle")
            if not name or et not in VALID_TYPES or hv not in VALID_VEHICLES:
                rejected.append((name, et, hv)); continue
            em.upsert(
                master, name,
                country=(rec.get("country_of_incorporation") or "").upper() or None,
                entity_type=et, holding_vehicle=hv,
                confidence=rec.get("confidence", "medium"), basis="web",
                evidence=rec.get("evidence"), source=rec.get("source_url"),
                ticker=ticker,
            )
            merged += 1
    em.save(master)
    return merged, rejected, em.stats(master)


if __name__ == "__main__":
    n, bad, st = merge(sys.argv[1:])
    print(f"merged {n} entity records; master now {st}")
    for b in bad:
        print("  REJECTED (schema):", b)
