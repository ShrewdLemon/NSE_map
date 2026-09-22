"""Pull agent records out of saved tool results and into registers.

Every large tool result lands on disk, so collection costs nothing: this walks
the dump, keeps the records that actually carry holders, and refuses to let a
headline-only record overwrite a register already built from a filing.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
import ingest_nimble as ing

DUMP = Path("/root/.claude/projects/-home-user-NSE-map/"
            "7a8d0610-d716-5bf0-aa30-fa6dca1fd61f/tool-results")


def records(paths):
    out = []
    for f in paths:
        try:
            d = json.loads(Path(f).read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        content = d.get("output", {}).get("content") if isinstance(d, dict) else None
        if content is None and isinstance(d, list):
            content = d
        if not isinstance(content, list):
            continue
        out += [r for r in content if isinstance(r, dict) and r.get("ticker")]
    return out


def run(paths=None):
    paths = paths or sorted(DUMP.glob("*.txt"), key=lambda p: p.stat().st_mtime)
    idx = json.load(open("data/nifty50.json"))
    sectors = {c["ticker"]: c["sector"] for c in idx["constituents"]}
    wanted = set(sectors)

    best = {}
    for r in records(paths):
        t = r["ticker"].strip()
        if t not in wanted:
            continue
        size = len(r.get("promoter_group") or []) + len(r.get("public_holders") or [])
        if size and size > best.get(t, (0, None))[0]:
            best[t] = (size, r)

    # A register already parsed from a filing beats a thinner agent record.
    final = []
    for t, (size, r) in best.items():
        f = Path(f"data/registers/{t}.json")
        if f.exists():
            old = json.loads(f.read_text())
            have = len(old.get("promoter_group", [])) + len(old.get("public_holders", []))
            if have >= size:
                continue
        final.append(r)

    written, warns = ing.ingest(final, sectors)
    print(f"updated {len(written)} registers: {sorted(written)}")
    for w in warns:
        print("  WARN", w)
    return written


if __name__ == "__main__":
    run(sys.argv[1:] or None)
