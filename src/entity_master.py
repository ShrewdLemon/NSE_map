"""Persistent name -> entity-facts map, shared across companies.

Entity type and domicile are facts about the world, so once an entity is
verified it never needs researching again. Promoter status is deliberately NOT
stored here: it is company-specific and lives in data/promoters_<TICKER>.json.
"""
import json
from datetime import date
from pathlib import Path

from normalize import normalize

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "entities.json"


def load(path=DEFAULT_PATH):
    if Path(path).exists():
        return json.loads(Path(path).read_text())
    return {"version": 1, "updated": None, "entities": {}}


def save(master, path=DEFAULT_PATH):
    master["updated"] = date.today().isoformat()
    Path(path).write_text(json.dumps(master, indent=2, sort_keys=True))
    return path


def get(master, holder_name):
    return master["entities"].get(normalize(holder_name))


def upsert(master, holder_name, *, country, entity_type, holding_vehicle,
           confidence, basis, evidence=None, source=None, ticker=None):
    key = normalize(holder_name)
    rec = master["entities"].get(key, {"first_seen": date.today().isoformat(),
                                       "seen_in": []})
    rec.update({
        "display_name": holder_name,
        "country": country,
        "entity_type": entity_type,
        "holding_vehicle": holding_vehicle,
        "confidence": confidence,
        "basis": basis,
        "evidence": evidence,
        "source": source,
        "verified_on": date.today().isoformat(),
    })
    if ticker and ticker not in rec["seen_in"]:
        rec["seen_in"].append(ticker)
    master["entities"][key] = rec
    return rec


def stats(master):
    ents = master["entities"].values()
    return {
        "total": len(master["entities"]),
        "high_confidence": sum(1 for e in ents if e.get("confidence") == "high"),
        "web_verified": sum(1 for e in ents if e.get("basis") == "web"),
    }
