"""Parse a Bloomberg OWN (Security Ownership) export into clean holder records."""
import json
import re
import sys
from pathlib import Path

import openpyxl

# Bloomberg pads empty cells with spaces / non-breaking spaces.
BLANK = {"", " ", "\xa0", "None", "-", "--"}


def clean(v):
    if v is None:
        return None
    s = str(v).replace("\xa0", " ").strip()
    return None if s in BLANK else s


def num(v):
    """Bloomberg leaves a holder's pre-entry quarters blank; treat as no position."""
    if isinstance(v, (int, float)):
        return int(v)
    s = clean(v)
    if s is None:
        return None
    s = s.replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return None


def find_header(ws):
    """Locate the row carrying 'Holder Name' — the export's banner height varies."""
    for row in ws.iter_rows(min_row=1, max_row=30):
        for cell in row:
            if clean(cell.value) == "Holder Name":
                return cell.row, cell.column
    raise SystemExit("could not find a 'Holder Name' header row")


def parse(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    hrow, hcol = find_header(ws)

    header = [clean(c.value) for c in ws[hrow]]
    # Quarter columns are everything after Holder Type that looks like Q#/YYYY.
    quarters = [
        (i, re.sub(r"[^\w/]", "", h))
        for i, h in enumerate(header)
        if h and re.match(r"^Q\d/\d{4}", h)
    ]

    # Ticker / ISIN live in the free-text banner above the table.
    banner = " ".join(
        clean(ws.cell(row=r, column=1).value) or "" for r in range(1, hrow)
    )
    isin = re.search(r"ISIN\s+([A-Z0-9]{12})", banner)
    company = None
    for r in range(1, hrow):
        t = clean(ws.cell(row=r, column=1).value) or ""
        if "ISIN" in t:
            company = t.split("ISIN")[0].strip()
            break

    records = []
    for row in ws.iter_rows(min_row=hrow + 1, max_row=ws.max_row):
        vals = [c.value for c in row]
        name = clean(vals[1]) if len(vals) > 1 else None
        if not name or name == "Holder Name":
            continue
        records.append(
            {
                "rank": num(vals[0]),
                "holder_name": name,
                "portfolio_name": clean(vals[2]) if len(vals) > 2 else None,
                "bloomberg_holder_type": clean(vals[3]) if len(vals) > 3 else None,
                "quarters": {q: num(vals[i]) for i, q in quarters},
            }
        )

    return {
        "company": company,
        "isin": isin.group(1) if isin else None,
        "quarter_labels": [q for _, q in quarters],
        "holders": records,
    }


if __name__ == "__main__":
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    data = parse(src)
    out.write_text(json.dumps(data, indent=2))
    print(f"company: {data['company']}  isin: {data['isin']}")
    print(f"quarters: {data['quarter_labels']}")
    print(f"holders: {len(data['holders'])}")
