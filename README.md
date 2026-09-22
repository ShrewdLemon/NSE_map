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
