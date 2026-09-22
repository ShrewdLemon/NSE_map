"""Assemble a RELIANCE holder register from public filings.

Unlike the Anand Rathi run, there is no Bloomberg OWN export here. A SEBI
shareholding pattern names every promoter group member but only those public
holders above 1%, so the public side is supplemented with fund-house and
institutional holdings from ownership aggregators.

Percentages are converted to share counts against shares outstanding. A
quarter with no sourced figure is left null rather than carried forward.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Percentages in the filing and in aggregator tables are on the SCRR basis
# (A)+(B)+(C2), which EXCLUDES the 243,159,324 shares underlying depository
# receipts. Using the 13,532,472,634 grand total instead inflates every
# converted share count by about 1.8%. Verified by backing the denominator out
# of holders that publish both a percentage and a share count.
SHARES_OUT = 13_289_313_310
GRAND_TOTAL_INCL_DRS = 13_532_472_634
QUARTERS = ["Jun/2025", "Sep/2025", "Dec/2025", "Mar/2026", "Jun/2026"]

# --- Promoter & promoter group, exact share counts as filed for Jun 2026 ----
PROMOTER_INDIVIDUALS = {
    "K D Ambani": 31_482_644, "Akash M Ambani": 16_104_042,
    "Anant M Ambani": 16_104_042, "Isha M Ambani": 16_104_042,
    "Mukesh D Ambani": 16_104_040, "Nita M Ambani": 16_104_042,
}
PROMOTER_ENTITIES = {
    "Srichakra Commercials LLP": 1_479_199_658,
    "Devarshi Commercials LLP": 1_091_138_920,
    "Karuna Commercials LLP": 1_091_138_920,
    "Tattvam Enterprises LLP": 1_091_138_920,
    "Reliance Industries Holding Private Ltd": 608_030_142,
    "Reliance Industrial Investments and Holdings Ltd": 481_884_012,
    "Reliance Services and Holdings Limited": 343_765_640,
    "Samarjit Enterprises LLP": 249_250_548,
    "Sikka Ports & Terminals Limited": 70_000_000,
    "Shrikrishna Tradecom LLP": 28_675_930,
    "Shreeji Comtrade LLP": 28_675_930,
    "Svar Enterprises LLP": 27_178_734,
    "Reliance Welfare Association": 10_689_994,
    "Vasuprada Enterprises LLP": 2_631_850,
    "Exotic Officeinfra Private Limited": 55_348,
    "Carat Holdings and Trading Co Pvt Ltd": 21_902,
    "Neutron Enterprises Private Limited": 3_698,
    "Futura Commercials Private Limited": 3_628,
    "Shripal Enterprises LLP": 432, "Vishatan Enterprises LLP": 432,
    "Janardan Commercials LLP": 432, "Harinarayan Enterprises LLP": 432,
    "Chhatrabhuj Enterprises LLP": 432, "Chakresh Enterprises LLP": 432,
    "Chakradhar Commercials LLP": 432, "Chakradev Enterprises LLP": 432,
    "Bhuvanesh Enterprises LLP": 430, "Kankhal Trading LLP": 430,
    "Pavana Enterprises LLP": 430, "Pitambar Enterprises LLP": 430,
    "Rishikesh Enterprises LLP": 430, "Taran Enterprises LLP": 430,
    "Trilokesh Commercials LLP": 430, "Badri Commercials LLP": 430,
    "Ajitesh Enterprises LLP": 430, "Adisesh Enterprises LLP": 430,
    "Abhayaprada Enterprises LLP": 430,
    "Kamalakar Enterprises LLP": 426, "Narahari Enterprises LLP": 426,
    "Pinakin Commercials Private Limited": 216,
    "Elakshi Commercials Private Limited": 216,
}
# Promoter group members holding no shares (the filing lists 51 members total).
PROMOTER_NIL = [
    "Reliance Life Sciences Private Limited",
    "Jamnagar Utilities and Power Private Limited",
    "Tiruttani Infralog Private Limited",
    "Petroleum Trust through Trustees for sole beneficiary RIIHL",
]

# --- Holders with a percentage series, oldest quarter first -----------------
# Domestic fund houses, five quarters.
FUND_HOUSES = {
    "SBI Mutual Fund":              [2.496, 2.527, 2.481, 2.500, 2.576],
    "ICICI Prudential Mutual Fund": [1.471, 1.673, 1.557, 1.578, 1.771],
    "HDFC Mutual Fund":             [0.688, 0.727, 0.782, 0.891, 0.979],
    "UTI Mutual Fund":              [0.753, 0.781, 0.811, 0.862, 0.905],
    "Nippon India Mutual Fund":     [0.771, 0.811, 0.824, 0.855, 0.877],
    "Kotak Mahindra Mutual Fund":   [0.345, 0.397, 0.317, 0.334, 0.398],
    "Mirae Asset Mutual Fund":      [0.246, 0.249, 0.228, 0.284, 0.362],
    "Aditya Birla Sun Life Mutual Fund": [0.332, 0.332, 0.341, 0.348, 0.331],
    "Axis Mutual Fund":             [0.277, 0.262, 0.294, 0.271, 0.250],
    "Franklin Templeton Mutual Fund": [0.162, 0.154, 0.153, 0.169, 0.174],
    "Tata Mutual Fund":             [0.163, 0.168, 0.155, 0.144, 0.170],
    "Bandhan Mutual Fund":          [0.160, 0.156, 0.152, 0.154, 0.167],
    "Canara Robeco Mutual Fund":    [0.135, 0.140, 0.142, 0.136, 0.141],
    "DSP Mutual Fund":              [0.043, 0.045, 0.046, 0.044, 0.125],
    "Invesco Mutual Fund":          [0.025, 0.070, 0.060, 0.051, 0.108],
    "Edelweiss Mutual Fund":        [0.090, 0.100, 0.090, 0.076, 0.084],
    "HSBC Mutual Fund":             [0.071, 0.077, 0.078, 0.114, 0.080],
    "Sundaram Mutual Fund":         [0.094, 0.094, 0.092, 0.090, 0.080],
    "Baroda BNP Paribas Mutual Fund": [0.054, 0.056, 0.053, 0.055, 0.052],
    "PPFAS Mutual Fund":            [0.056, 0.056, 0.059, 0.026, 0.044],
}
# Named in the filing as above 1%; the filing does not reach back to Jun 2025.
NAMED_PUBLIC = {
    "Life Insurance Corporation of India": [None, 6.94, 6.82, 6.80, 6.88],
    "NPS Trust":                           [None, 1.10, 1.29, 1.42, 1.55],
}
# Foreign holders, aggregator point-in-time only.
FOREIGN_POINT = {
    "Vanguard Group Inc/The": 295_667_028,
    "Blackrock Inc": 255_773_102,
    "Government Pension Fund Global": 105_494_998,
}


def pct_series(pcts):
    return {q: (None if p is None else round(p / 100 * SHARES_OUT))
            for q, p in zip(QUARTERS, pcts)}


def latest_only(shares):
    return {q: (shares if q == QUARTERS[-1] else None) for q in QUARTERS}


def build():
    holders = []
    for name, sh in PROMOTER_INDIVIDUALS.items():
        holders.append({"holder_name": name, "portfolio_name": None,
                        "bloomberg_holder_type": "Individual",
                        "quarters": latest_only(sh)})
    for name, sh in PROMOTER_ENTITIES.items():
        holders.append({"holder_name": name, "portfolio_name": None,
                        "bloomberg_holder_type": "Institution",
                        "quarters": latest_only(sh)})
    for name in PROMOTER_NIL:
        holders.append({"holder_name": name, "portfolio_name": None,
                        "bloomberg_holder_type": "Institution",
                        "quarters": {q: 0 for q in QUARTERS}})
    for src in (FUND_HOUSES, NAMED_PUBLIC):
        for name, pcts in src.items():
            holders.append({"holder_name": name, "portfolio_name": None,
                            "bloomberg_holder_type": "Institution",
                            "quarters": pct_series(pcts)})
    for name, sh in FOREIGN_POINT.items():
        holders.append({"holder_name": name, "portfolio_name": None,
                        "bloomberg_holder_type": "Institution",
                        "quarters": latest_only(sh)})

    holders.sort(key=lambda h: -(h["quarters"][QUARTERS[-1]] or 0))
    for i, h in enumerate(holders, 1):
        h["rank"] = i
    return {"company": "RELIANCE INDUSTRIES LTD", "isin": "INE002A01018",
            "quarter_labels": QUARTERS, "holders": holders}


if __name__ == "__main__":
    data = build()
    (ROOT / "output" / "holders_raw_RELIANCE.json").write_text(json.dumps(data, indent=2))
    prom = sum(PROMOTER_INDIVIDUALS.values()) + sum(PROMOTER_ENTITIES.values())
    print(f"holders: {len(data['holders'])}  quarters: {QUARTERS}")
    print(f"promoter rows: {len(PROMOTER_INDIVIDUALS)+len(PROMOTER_ENTITIES)+len(PROMOTER_NIL)}"
          f" (51 members per the filing)")
    print(f"promoter shares: {prom:,} = {prom/SHARES_OUT*100:.2f}% on the SCRR basis "
          f"(aggregators report 50.48% for Jun 2026)")
    for label, pct, want in [("SBI MF", 2.62, 347_942_145), ("LIC", 6.88, 915_033_063)]:
        got = round(pct / 100 * SHARES_OUT)
        print(f"  check {label:<8} {pct}% -> {got:,} vs published {want:,} "
              f"(delta {abs(got-want)/want*100:.2f}%)")
