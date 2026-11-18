#!/usr/bin/env python3
"""
Build the snapshot of public biodiversity records that `seed_local` plants.

Why this exists at all: an observation in Geonity is a species, a place and a
moment. All three are published as open data by GBIF (the Global Biodiversity
Information Facility), so the realistic half of a development dataset can be
rebuilt from a public source instead of extracted from production.

What it keeps, and what it never fetches
----------------------------------------
A GBIF occurrence record also carries the **name of the person who made the
observation** — `recordedBy`, `identifiedBy`, `rightsHolder`, and in iNaturalist
records a nickname. None of those are written to the snapshot: `KEEP` below is an
allow-list, and anything outside it is dropped here, at fetch time, so no
personal field ever reaches the repository or a local database. The `assert` at
the end of `strip()` is what makes that a check rather than a hope.

The query is restricted to `license=CC0_1_0`, so every record kept is in the
public domain and can live in a public repository.

Usage:

    python3 local_dev/fetch_gbif_sample.py             # rewrite local_dev/gbif_sample.json
    python3 local_dev/fetch_gbif_sample.py --limit 50  # fewer records per theme

The output is committed. Running this again is only needed to refresh or widen
the sample; `seed_local` never calls the network.
"""

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://api.gbif.org/v1/occurrence/search"

# Fields copied into the snapshot. Everything else — including every field that
# names a person — is discarded. Add to this list only after checking what the
# field contains.
KEEP = (
    "key",
    "scientificName",
    "species",
    "family",
    "order",
    "class",
    "decimalLatitude",
    "decimalLongitude",
    "coordinateUncertaintyInMeters",
    "eventDate",
    "iucnRedListCategory",
    "datasetName",
    "license",
)

# Fields known to carry personal data. Never keep one of these; the assertion
# below fails loudly if one is ever added to KEEP by accident.
PERSONAL = (
    "recordedBy",
    "recordedByIDs",
    "identifiedBy",
    "identifiedByIDs",
    "rightsHolder",
    "occurrenceID",
    "references",
    "http://unknown.org/nick",
    "media",
    "extensions",
)

# One theme per project in the sample. `taxonKey` values are GBIF's own:
# 212 = class Aves, 797 = order Lepidoptera.
THEMES = {
    "birds-ebro": {
        "about": "Birds in the middle Ebro valley (Aragón and around it)",
        "params": {
            "taxonKey": 212,
            "decimalLatitude": "40.0,42.9",
            "decimalLongitude": "-2.2,0.8",
        },
    },
    "lepidoptera-spain": {
        "about": "Butterflies and moths across Spain",
        "params": {
            "taxonKey": 797,
            "country": "ES",
        },
    },
}

# Only recent records, so the seeded dataset does not open on screens that say
# "last contribution 2 years ago". GBIF publishes with a lag of some weeks, so the
# newest record available is usually about a month old however wide this window is.
RECENT_DAYS = 150

COMMON = {
    "license": "CC0_1_0",          # public domain: safe to commit
    "hasCoordinate": "true",
    "hasGeospatialIssue": "false",
    "basisOfRecord": "HUMAN_OBSERVATION",
}


def window(days):
    today = date.today()
    return f"{today - timedelta(days=days)},{today}"


def strip(record):
    """Reduce a GBIF record to the fields in KEEP, dropping everything else."""
    kept = {name: record.get(name) for name in KEEP if record.get(name) is not None}
    assert not set(kept) & set(PERSONAL), f"personal field kept: {set(kept) & set(PERSONAL)}"
    return kept


def fetch(theme, limit):
    params = dict(COMMON, **THEMES[theme]["params"], limit=limit,
                  eventDate=window(RECENT_DAYS))
    url = f"{API}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
        payload = json.load(response)
    records = [strip(r) for r in payload["results"]]
    # Keep only records that have everything seed_local needs.
    records = [
        r for r in records
        if r.get("species") and r.get("eventDate")
        and r.get("decimalLatitude") is not None and r.get("decimalLongitude") is not None
    ]
    # One record per coordinate, so the map is not a single pile of pins.
    seen, spread = set(), []
    for record in records:
        cell = (round(record["decimalLatitude"], 2), round(record["decimalLongitude"], 2))
        if cell in seen:
            continue
        seen.add(cell)
        spread.append(record)
    spread.sort(key=lambda r: r["eventDate"], reverse=True)
    return url, payload["count"], spread


def main():
    global RECENT_DAYS  # noqa: PLW0603 — set once from the command line

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=300, help="records requested per theme")
    parser.add_argument("--days", type=int, default=RECENT_DAYS,
                        help=f"how far back to look. Default {RECENT_DAYS}.")
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gbif_sample.json"),
    )
    options = parser.parse_args()
    RECENT_DAYS = options.days

    snapshot = {
        "source": "GBIF occurrence search API (api.gbif.org), no API key needed",
        "license": "CC0 1.0 — the query asks for license=CC0_1_0 only",
        "retrieved": date.today().isoformat(),
        "event_dates": window(RECENT_DAYS),
        "built_by": "local_dev/fetch_gbif_sample.py",
        "fields_kept": list(KEEP),
        "note": (
            "Fields naming the observer (recordedBy, identifiedBy, rightsHolder, "
            "nicknames) are never fetched into this file. The people in the local "
            "dataset are invented by seed_local."
        ),
        "themes": {},
    }

    for theme, meta in THEMES.items():
        url, total, records = fetch(theme, options.limit)
        snapshot["themes"][theme] = {
            "about": meta["about"],
            "query": url,
            "matching_in_gbif": total,
            "records": records,
        }
        print(f"{theme}: kept {len(records)} of {total} matching records")

    with open(options.out, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=1, sort_keys=False)
        handle.write("\n")
    print(f"wrote {options.out}")


if __name__ == "__main__":
    main()
