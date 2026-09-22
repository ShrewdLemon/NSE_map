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

# --- RELIANCE: a second company on the same pipeline ---------------------
rel_holders = json.loads((ROOT / "output" / "holders_raw_RELIANCE.json").read_text())["holders"]
rel_reg = json.loads((ROOT / "data" / "promoters_RELIANCE.json").read_text())
rel_prom, rel_issues = match_promoters(rel_holders, rel_reg)

check("bonus factor is per-company, not hard-coded",
      (json.loads((ROOT / "data" / "promoters_ANANDRATHI.json").read_text())["bonus_factor"],
       rel_reg["bonus_factor"]), (2, 1))
check("all 51 filed promoter group members are matched", len(rel_prom), 51)
check("registry reconciles to its stated total",
      sum(p["shares_filed"] for p in rel_reg["promoter_group"]),
      rel_reg["promoter_total_shares_filed"])
check("no matcher disagreement on holders that actually hold", rel_issues, [])
for nm in ("Life Insurance Corporation of India", "NPS Trust", "SBI Mutual Fund",
           "Vanguard Group Inc/The"):
    check(f"{nm} is not a promoter", nm in rel_prom, False)
# Percentages are on the SCRR basis, which excludes shares underlying DRs.
# Using the grand total instead would overstate every converted count.
import build_register
rel_register = json.loads((ROOT / "data" / "registers" / "RELIANCE.json").read_text())
SCRR, GRAND_TOTAL_INCL_DRS = 13_289_313_310, 13_532_472_634
check("percentage denominator excludes depository receipts",
      rel_register["shares_scrr"], SCRR)
check("denominator reproduces a published share count within rounding",
      abs(round(6.88 / 100 * SCRR) - 915_033_063) / 915_033_063 < 0.001, True)

# The denominator is recovered from the data, not trusted from the header, so a
# register that states the DR-inclusive grand total is corrected rather than
# propagated. This is the guard that stops the Reliance mistake recurring on
# any of the other forty-nine companies.
# Recovery works off percentages rounded to six places, so it lands near the
# true base rather than exactly on it. What matters is that it rejects the
# DR-inclusive total, which is 1.8% out - hundreds of times the rounding noise.
recovered = build_register.resolve_denominator(
    {**rel_register, "shares_scrr": GRAND_TOTAL_INCL_DRS})[0]
check("a stated grand total is overridden by what the holders imply",
      abs(recovered - SCRR) / SCRR < 0.0001, True)
check("the override does not simply keep the grand total",
      recovered != GRAND_TOTAL_INCL_DRS, True)
check("a correct stated denominator is left alone",
      build_register.resolve_denominator(rel_register)[0], SCRR)
# Too few disagreeing holders must not be enough to move it.
check("one outlier cannot move the denominator",
      build_register.resolve_denominator(
          {"shares_scrr": SCRR, "promoter_group": [],
           "public_holders": [{"holder_name": "x", "shares": 100, "pct": 50.0}]})[0],
      SCRR)

# A promoter group member filed as holding nil is a fact, not a missing figure.
rel_raw = json.loads((ROOT / "output" / "holders_raw_RELIANCE.json").read_text())
nil_member = next(h for h in rel_raw["holders"]
                  if h["holder_name"].startswith("Reliance Life Sciences"))
check("a filed nil holding stays zero rather than becoming null",
      nil_member["quarters"][rel_raw["quarter_labels"][-1]], 0)

# --- the entity cache must round-trip every category a rule can emit -------
# The master is consulted BEFORE the rules, so anything cached wrongly silently
# overrides the rule that produced it. A rule returning 'Government' once cached
# entity_type None, which came back as an unclassified holder on the next run.
import build as pipeline
import rules as rules_mod

_RULE_CATEGORIES = set()
for _name in ("SBI Mutual Fund", "Life Insurance Corporation of India",
              "President of India", "NPS Trust", "LICI ULIP-Growth Fund",
              "SBI Nifty 50 ETF", "HDFC Trustee Company Limited"):
    _r = rules_mod.classify(_name, normalize(_name), "Institution")
    if _r:
        _RULE_CATEGORIES.add(_r[0])

for _cat in sorted(_RULE_CATEGORIES):
    _type = pipeline._TYPE_FOR_CATEGORY.get(_cat)
    check(f"cache can represent {_cat!r}", bool(_type), True)
    _back, _ = categorize(is_promoter=False, bloomberg_type="Institution",
                          country=pipeline.country_for_category(_cat),
                          entity_type=_type,
                          holding_vehicle=pipeline._VEHICLE_FOR_CATEGORY.get(_cat))
    check(f"{_cat!r} survives a cache round-trip", _back, _cat)

# And nothing may be cached that cannot round-trip.
check("an unmappable category is never cached",
      pipeline._TYPE_FOR_CATEGORY.get("Individual"), None)
# 'Government' is the domestic bucket; its foreign counterpart is named.
check("the domestic sovereign bucket carries a domicile",
      pipeline.country_for_category("Government"), "IN")
check("a foreign category carries none",
      pipeline.country_for_category("Foreign Government"), None)

# --- ingest: the airlock between a web agent and the pipeline --------------
import ingest_nimble as ing

check("a quarter end becomes a Book1 label", ing.label("2026-06-30"), "Jun/2026")
check("a malformed date yields no label", ing.label("Q1 FY27"), None)

# Filing tables carry subtotal and section-heading rows beside real holders.
# One slipping through would double-count an entire category.
for junk in ("Total", "Sub-Total (A)(1)", "Promoter & Promoter Group",
             "Mutual Funds", "Bodies Corporate", "Public", "Any Other (specify)",
             "Foreign Portfolio Investors", "Resident Individuals", "12,345",
             "Total (A)+(B)+(C)", "Total (A)+(B)+(C2)", "(A)(1) Sub-Total",
             "Sub Total - (B)(3)", "Mutual Funds (i)",
             # A category total wearing a holder's clothes. Bharti Airtel came
             # back with these above the named funds inside them, which pushed
             # its named holders to 111% of the share base.
             "Mutual Funds (total)", "Insurance Companies (total)", "Banks (total)",
             "Foreign Portfolio Investors Category I",
             "Foreign Portfolio Investors - Cat II", "Total Mutual Funds",
             "Alternate Investment Funds", "NBFCs registered with RBI",
             "Central Government/President of India", "Clearing Members",
             "Institutions - Domestic", "Non-Institutions", "FPIs", "DIIs"):
    check(f"aggregate row rejected: {junk!r}", ing._clean_name(junk), None)
# A real name may carry parentheses too; only a single letter, roman numeral
# or digit inside them reads as a table reference.
for real in ("SBI Mutual Fund", "Life Insurance Corporation of India",
             "Vanguard Group Inc/The", "Rekha Rakesh Jhunjhunwala",
             "Alpha Holdings (India) Pvt Ltd", "Nestle (Deutschland) AG",
             # Scheme-level names contain a class word but are real holders.
             "SBI ELSS Tax Saver Fund", "UTI Multi Cap Fund",
             "HDFC Mutual Fund - HDFC Technology Fund",
             "LICi New Pension Plus Secured Fund", "Government of Singapore - E",
             "NPS Trust A/C - SBI PF NPS Jeevan Swarna Retirement"):
    check(f"real holder kept: {real!r}", ing._clean_name(real), real)

# 'Trusts' is a category heading; a named trust is a holder.
check("a category heading is not a holder", ing._clean_name("Trusts"), None)
check("a named trust is a holder",
      ing._clean_name("NPS Trust- A/C UTI Retirement Solutions"),
      "NPS Trust- A/C UTI Retirement Solutions")

sample = {"ticker": "TEST", "company_name": "Test Ltd", "quarter_end": "2026-06-30",
          "total_shares_scrr": 1_000_000, "promoter_pct": 50.0, "has_promoter": True,
          "promoter_group": [{"filed_name": "Alpha Holdings Pvt Ltd",
                              "shares_filed": 500_000, "pct": 50.0},
                             {"filed_name": "Total", "shares_filed": 500_000}],
          "public_holders": [{"holder_name": "SBI Mutual Fund", "shares": 100_000,
                              "pct": 10.0},
                             {"holder_name": "Alpha Holdings Pvt Ltd",
                              "shares": 500_000, "pct": 50.0}],
          "source_urls": ["https://example.com/shp.pdf"]}
reg, warns = ing.normalise(sample)
check("subtotal row dropped from the promoter group", len(reg["promoter_group"]), 1)
check("a promoter cannot also be a public holder", len(reg["public_holders"]), 1)
check("the surviving public holder is the right one",
      reg["public_holders"][0]["holder_name"], "SBI Mutual Fund")
check("the duplicate is reported, not swallowed",
      any("duplicate a promoter name" in w for w in warns), True)

# --- cross-check: corroborate, never silently rewrite ----------------------
import crosscheck

reg_for_xc = {"ticker": "TEST", "promoter_pct": 50.0, "shares_scrr": 1_000_000,
              "as_of": "2026-06-30", "promoter_group": [], "public_holders": []}
check("agreement within tolerance raises nothing",
      crosscheck.compare({"promoter_pct": 50.3, "total_shares_scrr": 1_000_500,
                          "quarter_end": "2026-06-30"}, reg_for_xc), [])
check("a promoter percentage disagreement is reported",
      len(crosscheck.compare({"promoter_pct": 42.0}, reg_for_xc)), 1)
check("a share base disagreement is reported",
      len(crosscheck.compare({"promoter_pct": 50.0,
                              "total_shares_scrr": 1_200_000}, reg_for_xc)), 1)

target = {"ticker": "TEST", "promoter_group": [{"filed_name": "Alpha Holdings Pvt Ltd"}],
          "public_holders": [{"holder_name": "SBI Mutual Fund"}]}
added = crosscheck.supplement(
    {"top_holders": [{"holder_name": "SBI Mutual Fund", "pct": 10.0},
                     {"holder_name": "Alpha Holdings Pvt Ltd", "pct": 50.0},
                     {"holder_name": "ICICI Prudential Mutual Fund", "pct": 3.0}]},
    target)
check("only the genuinely new holder is added", added, 1)
check("a supplemented holder is tagged with its weaker provenance",
      "cross-check" in target["public_holders"][-1]["provenance"], True)

# --- workbook: sheet names must survive Excel's restrictions ---------------
from write_workbook import sheet_name
check("an ampersand ticker is a legal sheet name", sheet_name("M&M"), "M&M")
check("a slash is replaced, not passed through", sheet_name("A/B"), "A-B")
check("a long name is truncated to Excel's limit",
      len(sheet_name("X" * 40)), 31)

if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
