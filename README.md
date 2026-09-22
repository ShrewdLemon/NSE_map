# NSE_map — shareholder category mapping

Maps the holder names in a Bloomberg `OWN` (Security Ownership) export onto a
fixed shareholder-category taxonomy, for Indian listed equities.

## The problem

A Bloomberg ownership export tells you *who* holds the stock, but its
`Holder Type` column has only two values — `Institution` and `Individual`.
The target taxonomy (`data/taxonomy.json`) has 13. Getting from one to the
other needs three independent judgments per name:

| Axis | Question | Source of truth |
|---|---|---|
| Promoter status | in the promoter & promoter group? | the company's filed shareholding pattern |
| Domicile | where is *this named entity* incorporated? | web |
| Entity type | AMC / insurer / bank / pension / sovereign / corporate | web |

They collapse into one label, and **promoter wins over the other two** — an
entity in the promoter group is `Promoter` even when it is an insurance
broker or an operating company.

## Pipeline

There are two ways in, because there are two kinds of source. A Bloomberg
`OWN` export names the long tail of holders but knows nothing about promoter
status; a filed shareholding pattern is authoritative on promoters but only
names public holders above 1%. Both converge on the same holder rows.

```
Bloomberg .xlsx                    data/registers/<TICKER>.json
      |                                      |
      v                                      v
  parse_bloomberg.py                   build_register.py
  strip the banner, find the           recover the SCRR denominator,
  header row, type the quarters        emit holder rows + the registry
      |                                      |
      +------------------+-------------------+
                         v
  promoters.py           overlay filed Table II names  ... company-specific
      |
      v
  rules.py               name-only deterministic rules ... no web calls
      |
      v
  entity_master.py       cached entity facts           ... cross-company
      |
      v
  categorize.py          collapse the three axes into one label
      |
      v
  write_output.py        Book1 layout + audit columns
```

Each stage only handles what it can settle for certain and passes the rest
down. Whatever reaches the end unresolved is flagged `REVIEW` rather than
guessed.

### Promoter matching is verified twice

`promoters.py` runs two independent matchers over every row and reports any
disagreement instead of picking a winner:

* **token** — normalised token-set match, so `Gupta Pradeep Kumar` reconciles
  with the filing's `Pradeep kumar gupta`. Subset matching is allowed only
  between two personal names, otherwise `Anand Rathi` would swallow
  `Anand Rathi Financial Services Ltd`.
* **numeric** — a quarter's share count equalling the filed count × bonus
  factor. For Anand Rathi Wealth the factor is 2 (1:1 bonus), and Bloomberg
  additionally merges each individual's HUF into their personal row, so
  individual+HUF sums are candidate targets too.

### The entity master compounds

`data/entities.json` accumulates verified entity facts keyed on a normalised
name, so `ICICI Prudential Asset Management Co Ltd/India` and
`ICICI Prudential Asset Management Company Limited` resolve to one record.
Entity type and domicile are facts about the *entity*, so they are researched
once and reused on every later company. Promoter status is **not** cached —
it is company-specific and lives in `data/promoters_<TICKER>.json`.

## Rulings encoded

* **Promoter overrides** entity type and domicile.
* **Banks are classified by holding vehicle.** The taxonomy has a single,
  domicile-neutral `Bank` bucket, so a banking group whose stake sits with its
  asset-management arm is an AMC; one holding via custody or its own book is
  `Bank`.
* **`Foreign Pension Fund` was added** to the 12 Book1 categories. Book1 has
  `Domestic Pension Fund` with no foreign counterpart, which would force
  foreign retirement pools into `Foreign Insurance` or `Foreign AMC`.
* **Entity as named** — each holder is classified as the entity Bloomberg
  names, never its parent. `Jio BlackRock Asset Management Pvt Ltd` is a
  Domestic AMC; `Blackrock Inc` is a Foreign AMC.
* **`Value` columns are left blank.** The Bloomberg export carries share
  counts only.

## Run it

One company from a Bloomberg export:

```bash
python3 src/parse_bloomberg.py "data/<company>.xlsx" output/holders_raw.json
python3 src/build.py --registry data/promoters_<TICKER>.json --ticker <TICKER>
```

A whole index from filed shareholding patterns:

```bash
python3 src/build_nifty50.py                # one workbook for every constituent
python3 src/build_nifty50.py --unresolved   # what still needs research
python3 src/build_nifty50.py --only TCS INFY
```

Outputs land in `output/` as `.xlsx`, `.csv`, and `.json`. The index workbook
carries a Summary sheet, an Index totals rollup, a combined All holders sheet
and one sheet per company.

## Adding a company

A company is data, not code. Write `data/registers/<TICKER>.json`:

```jsonc
{
  "ticker": "ACME", "company": "Acme Industries Limited",
  "as_of": "2026-06-30", "quarters": ["Jun/2026"],
  "shares_scrr": 1000000000,          // optional: recovered if wrong or absent
  "promoter_pct": 51.2, "has_promoter": true,
  "promoter_group": [{"filed_name": "...", "shares_filed": 123, "pct": 0.1}],
  "public_holders": [{"holder_name": "...", "shares": 456, "pct": 0.5,
                      "pct_series": {"Mar/2026": 0.48, "Jun/2026": 0.5}}]
}
```

Then add the ticker to `data/nifty50.json` (or pass `--only`) and run. Names
already in the entity master resolve for free; only genuinely new entities
need research.

Coming from a Bloomberg export instead, keep the older path: parse the export
and hand-build `data/promoters_<TICKER>.json`, recording the bonus/split
factor when the export is adjusted and the filing is not.

### The denominator is recovered, not trusted

Indian filings quote percentages on the SCRR basis `(A)+(B)+(C2)`, which
excludes shares underlying depository receipts. Reliance publishes a
13,532,472,634 grand total and a 13,289,313,310 SCRR base; using the wrong one
inflates every converted share count by 1.8%. So `shares_scrr` is a hint, not
gospel: `resolve_denominator()` backs the real base out of holders that publish
both a share count and a percentage, and overrides the stated figure only when
at least three of them disagree by more than half a percent. One stale row
cannot move it.

## What the numbers are checked against

Reading fifty filings by machine produces wrong numbers sometimes. The point
of the checks below is that a wrong number should be visible rather than
plausible.

**The promoter rows against the filed percentage.** Every company's filed
promoter percentage is an independent check on the promoter rows parsed out of
its filing: multiply it by the share base and it should equal their sum. Each
company carries the verdict - `reconciled` (within 1%), `close` (within 10%),
`unreconciled`, or `unchecked` - on the Provenance sheet. A partial promoter
table is never presented as a complete one.

**The share base against the holders.** `shares_scrr` is a hint, not gospel.
The real denominator is recovered from holders that publish both a count and a
percentage, and the stated figure is overridden only when at least three of
them disagree by more than half a percent, so one stale row cannot move it.

**Each holding against its own percentage.** A count that exceeds the share
base is impossible, and there the percentage wins: SBI Life came back with
Government of Singapore holding 212% of the company. Where the two merely
disagree the filed count stands and the row is flagged, because either field
can be the wrong one - in that same filing SBI Mutual Fund's count is fine and
its percentage looks like 12.13 with a digit dropped. Guessing which to trust
would be inventing data.

The tolerance scales with the rounding in the percentage: a holding filed as
0.02% carries half a basis point of slack, which is a quarter of the figure.

## Known limits

**A shareholding pattern names every promoter but only public holders above
1%.** The long tail of smaller funds and FPIs is not in the filing, so named
holders cover well under 100% of each company's shares. The Provenance sheet
gives the covered fraction per company. A Bloomberg `OWN` export names that
tail, and the pipeline ingests one unchanged.

**The two promoter matchers are not independent here.** For a company built
from its filing, the register and the promoter registry are cut from the same
document, so the numeric matcher confirms arithmetic rather than corroborating
a second source. Only a separately sourced register - the Anand Rathi
Bloomberg export, for instance - makes the two genuinely independent.

**Layouts differ per company.** SEBI fixes the tables, not the column order or
the PDF's internal text order. Columns are read by repetition rather than
position for that reason, and a filing whose captions and rows are interleaved
by PDF extraction can still defeat it - which is what the reconciliation
verdict is for.

## Result for the NIFTY 50 (quarter ended 30 June 2026)

All 50 constituents, 1,372 named holders, 7 unclassified.

| Category | Rows | Companies | Shares held | Share |
|---|---:|---:|---:|---:|
| Promoter | 975 | 42 | 79,957,999,860 | 61.3% |
| Domestic AMC | 210 | 43 | 22,903,478,076 | 17.6% |
| Domestic Insurance | 66 | 42 | 13,565,487,353 | 10.4% |
| Foreign corporate | 13 | 8 | 3,822,141,212 | 2.9% |
| Foreign Government | 26 | 20 | 2,059,316,327 | 1.6% |
| Foreign AMC | 20 | 13 | 1,813,570,582 | 1.4% |
| Domestic corporate | 16 | 5 | 1,739,984,566 | 1.3% |
| Individual | 26 | 8 | 1,596,272,912 | 1.2% |
| Domestic Pension Fund | 10 | 10 | 1,521,469,793 | 1.2% |
| Government | 1 | 1 | 974,531,427 | 0.7% |
| Bank | 2 | 2 | 191,340,746 | 0.1% |
| unclassified | 7 | 6 | 244,805,996 | 0.2% |

Promoter reconciliation: 36 companies reconcile against their filed promoter
percentage, 4 are close, 1 does not, 6 could not be checked for want of a
published percentage, and 3 returned no holder data at all. Those three -
Maruti Suzuki, Max Healthcare and Nestle India - appear in the workbook with
no holders rather than being dropped, because dropping them would quietly turn
"the Nifty 50" into "the ones that worked".

How each row was settled: 975 from a filed promoter table, 276 by deterministic
name rules, 54 from web-verified entity research, 26 from a holder type, and 41
by the weaker legal-form fallbacks, which are flagged.

## Result for ANANDRATHI (Q2/2025 - Q3/2026)

All 102 holders classified, none left unresolved.

| Basis | Holders |
|---|---|
| Web-verified entity facts | 39 |
| Deterministic name rules | 38 |
| Filed shareholding pattern (promoter) | 17 |
| Bloomberg holder type (individuals) | 8 |

11 rows carry `REVIEW` — contestable calls surfaced rather than buried. The
`Bank` bucket is empty, which is a direct consequence of the holding-vehicle
ruling: every banking group on this register holds through its
asset-management arm rather than on its own book.

Two corrections worth noting, both caught by cross-checking automated research
against primary sources:

* Web research returned `managed_funds` for **Rawal Family Trust**, which would
  have made a private family trust a Domestic AMC. The shareholding pattern
  lists it under Public > Non-Institutions > Trusts, "acting through Rakesh
  Rawal".
* Web research returned `AU / bank` for **WBC Holdings LP**, reading the WBC
  ticker as Westpac. Bloomberg's own profile (1307537D:US) describes it as a
  US investment-management and broker-dealer partnership.

**Amit Rathi** is `Individual`, not `Promoter`: he was reclassified from
Promoter Group to Public with effect from 23 May 2025, before the window
opens, which exactly explains the 47.29% -> 42.71% drop in promoter holding.

## Result for RELIANCE (Jun 2025 - Jun 2026)

All 76 holders classified, none left unresolved.

| Basis | Holders |
|---|---|
| Filed shareholding pattern (promoter) | 51 |
| Deterministic name rules | 21 |
| Entity master cache | 4 |

**Input differs from the Anand Rathi run.** There is no Bloomberg `OWN` export
here, so the register is built from the filed shareholding pattern plus
fund-house and institutional holdings from ownership aggregators
(`src/build_reliance_register.py`). A shareholding pattern names every
promoter group member but only those public holders above 1%, so the ~1,360
individually unnamed FPIs are absent. Named holders cover 73.58% of the share
base; the rest is that unnamed tail.

All 51 filed promoter group members are matched, including the four that hold
no shares. Note that for this company the numeric matcher is **not**
independent evidence — register and registry are built from the same filing —
so the token matcher is doing the real work. On a Bloomberg-sourced register
the two are genuinely independent.

Two things the second company forced out of the code:

* **Bonus factor moved into the registry.** It was hard-coded at 2 for Anand
  Rathi's 1:1 bonus. Reliance needs 1, since register and filing are both
  post-bonus.
* **Percentages are on the SCRR basis**, `(A)+(B)+(C2)` = 13,289,313,310,
  which excludes the 243,159,324 shares underlying depository receipts. Using
  the 13,532,472,634 grand total would inflate every converted share count by
  about 1.8%. The denominator was verified by backing it out of holders that
  publish both a percentage and a share count.

A zero holding is no longer treated as numeric evidence, so the four
nil-holding promoter group members match on name alone without being reported
as matcher disagreements.
