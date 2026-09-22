"""Guards on the parts that would silently produce a wrong register."""
import json
import sys
from pathlib import Path

from categorize import categorize
from normalize import normalize
from promoters import match as match_promoters

ROOT = Path(__file__).resolve().parent.parent
FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


# --- normalisation ------------------------------------------------------
check("suffix/locale variants collapse",
      normalize("ICICI Prudential Asset Management Co Ltd/India"),
      normalize("ICICI Prudential Asset Management Company Limited"))
check("ampersand expands",
      normalize("Teachers Insurance & Annuity Association of America"),
      "teachers insurance and annuity association of america")
check("distinct entities stay distinct",
      normalize("Blackrock Inc") != normalize("Jio BlackRock Asset Management Pvt Ltd"),
      True)

# --- promoter overlay ---------------------------------------------------
holders = json.loads((ROOT / "output" / "holders_raw.json").read_text())["holders"]
registry = json.loads((ROOT / "data" / "promoters_ANANDRATHI.json").read_text())
promoters, issues = match_promoters(holders, registry)

check("registry reconciles to the filed total",
      sum(p["shares_filed"] for p in registry["promoter_group"]),
      registry["promoter_total_shares_filed"])
check("both matchers agree on every row", issues, [])
check("promoter row count", len(promoters), 17)
for nm in ("Anand Rathi", "Anand Rathi Financial Services Ltd",
           "Anand Rathi Insurance Brokers Ltd", "Gupta Pradeep Kumar"):
    check(f"{nm} is a promoter", nm in promoters, True)
# Reclassified out of the promoter group on 2025-05-23, before the window opens.
for nm in ("Rathi Amit", "Rawal Rakesh", "Azeez Feroze", "Azeez Family Trust",
           "Munix India Pvt Ltd", "ANANDRATHI HOUSING FIN LTD"):
    check(f"{nm} is not a promoter", nm in promoters, False)
check("a person's name does not match a company of the same family name",
      promoters["Anand Rathi"]["filed_names"], ["Anand rathi"])

# --- decision table -----------------------------------------------------
tax = set(json.loads((ROOT / "data" / "taxonomy.json").read_text())["categories"])
check("promoter overrides entity type",
      categorize(is_promoter=True, bloomberg_type="Institution", country="IN",
                 entity_type="insurer", holding_vehicle="insurance_float")[0],
      "Promoter")
check("bank holding via its asset manager is an AMC",
      categorize(is_promoter=False, bloomberg_type="Institution", country="US",
                 entity_type="bank", holding_vehicle="managed_funds")[0],
      "Foreign AMC")
check("bank holding on its own book is a Bank",
      categorize(is_promoter=False, bloomberg_type="Institution", country="DE",
                 entity_type="bank", holding_vehicle="own_balance_sheet")[0],
      "Bank")
check("custody also stays a Bank",
      categorize(is_promoter=False, bloomberg_type="Institution", country="US",
                 entity_type="bank", holding_vehicle="custody_only")[0],
      "Bank")
check("sovereign capital is Foreign Government",
      categorize(is_promoter=False, bloomberg_type="Institution", country="NO",
                 entity_type="sovereign_wealth_fund", holding_vehicle="sovereign_assets")[0],
      "Foreign Government")
check("every decision-table output is a valid category",
      all(categorize(is_promoter=False, bloomberg_type="Institution", country=c,
                     entity_type=t, holding_vehicle=v)[0] in tax
          for c in ("IN", "US")
          for t in ("asset_manager", "insurer", "bank", "pension_fund",
                    "sovereign_wealth_fund", "operating_company",
                    "private_family_trust", "broker", "other",
                    "exchange_traded_fund_trust")
          for v in ("managed_funds", "insurance_float", "pension_assets",
                    "sovereign_assets", "own_balance_sheet", "custody_only",
                    "operating_company_treasury")),
      True)

if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
