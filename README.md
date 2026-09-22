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

```
Bloomberg .xlsx
      |
      v
  parse_bloomberg.py     strip the banner, find the header row, type the quarters
      |
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

```bash
python3 src/parse_bloomberg.py "data/<company>.xlsx" output/holders_raw.json
python3 src/build.py --registry data/promoters_<TICKER>.json --ticker <TICKER>
```

Outputs land in `output/` as `.xlsx` (Book1 layout), `.csv`, and `.json`.

## Adding a company

1. Drop the Bloomberg export in `data/` and parse it.
2. Build `data/promoters_<TICKER>.json` from that company's filed
   shareholding pattern (Table II). Record the bonus/split factor if the
   Bloomberg counts are adjusted and the filing is not.
3. Run `build.py`. Names already in the entity master resolve for free;
   only genuinely new entities need research.

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
