"""Evidence-only Google Maps probes for four still-ranking Ontario FSAs.

Keeps every historical Google place and every successful tile. Newly observed
place URLs must resolve to a real business coordinate within 5 km of the
Statistics Canada reference coordinate. Capped Google feeds add LOWER BOUNDS
but never certify full coverage by themselves.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from research.recover_google_tiles import scan_tile, identity, RADIUS_KM
from research.scan_all_maps import distance_km
from finder.google_browser import scan_one, place_coordinates, resolve_place_coordinates
from finder.common import HumanVerificationRequired, SourceUnavailable

QUERIES = {
    "K7G": ("registered psychotherapist", "psychotherapy", "counselling", "mental health", "psychologist Gananoque", "counselling Gananoque"),
    "L7M": ("registered psychotherapist", "psychotherapy", "counselling", "mental health", "family counselling", "psychologist Burlington"),
    "N6M": ("registered psychotherapist", "psychotherapy", "counselling", "mental health", "family therapy", "psychologist London Ontario"),
    "N0L": ("Cindy Machado Machado Psychotherapy",),
}
OFFSETS = ((0, 0), (-2.5, 0), (2.5, 0), (0, -2.5), (0, 2.5))


def add_places(source, places):
    combined = {x["key"]: x for x in source.get("local_places", [])}
    for new in places:
        old = combined.get(new["key"])
        if old:
            for key in ("google_business_category", "google_category_evidence_url",
                        "google_category_checked_at"):
                if old.get(key) and not new.get(key):
                    new[key] = old[key]
        combined[new["key"]] = new
    source["local_places"] = list(combined.values())
    source["unique_observed_local_places"] = len(combined)


def run(code, checkpoint, seed, baseline, seconds):
    if code not in QUERIES:
        raise RuntimeError("Unexpected rescue FSA " + code)
    doc = json.loads(checkpoint.read_text())
    old = json.loads(seed.read_text())
    if code != doc.get("fsa") or code != old.get("fsa"):
        raise RuntimeError("Incorrect Google checkpoint identity")
    if not set(old.get("complete_tiles", {})).issubset(doc.get("complete_tiles", {})):
        raise RuntimeError("Original observed Google tiles missing")
    original = {p["key"] for p in doc.get("local_places", [])}
    candidates = json.loads(Path("research/ontario_all_populated_fsa_2021.json").read_text())["areas"]
    center_row = next((r for r in candidates if r["fsa"] == code), None)
    if not center_row:
        raise RuntimeError("Missing geographic reference")
    center = (center_row["lat"], center_row["lon"])
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    done = doc.setdefault("additional_provenance_queries", {})
    start = time.monotonic()
    with sync_playwright() as playwright:
        browser = playwright.firefox.launch_persistent_context(
            str(checkpoint.parent / "rescue-profile"), headless=True,
            viewport={"width": 1400, "height": 960}, locale="en-CA")
        try:
            for term in QUERIES[code]:
                for north, east in (OFFSETS[:1] if code == "N0L" else OFFSETS):
                    if time.monotonic() - start > seconds:
                        break
                    key = f"additional_20261123_v1|{code}|{north}|{east}|{term}"
                    if key in done:
                        continue
                    try:
                        tile = scan_tile(browser, code, center, north, east, 1, term, checkpoint.parent)
                        if not tile.get("map_area_search_verified"):
                            raise SourceUnavailable("No geographically verified source")
                        add_places(doc, tile["places"])
                        done[key] = tile
                    except (SourceUnavailable, HumanVerificationRequired, Exception) as exc:
                        doc.setdefault("additional_source_failures", {})[key] = (
                            type(exc).__name__ + ": " + str(exc))[:400]
                    finally:
                        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
                        checkpoint.write_text(json.dumps(doc, indent=2))
                if time.monotonic() - start > seconds:
                    break
            if code == "N0L":
                for key, tile in doc.get("complete_tiles", {}).items():
                    if not tile.get("unresolved"):
                        continue
                    remaining = []
                    for entry in tile["unresolved"]:
                        href = entry["url"]
                        coords = None
                        try:
                            coords, evidence_url = resolve_place_coordinates(browser, href, timeout_ms=18000)
                        except Exception:
                            pass
                        if coords is None:
                            remaining.append(entry)
                            continue
                        tile.setdefault("resolved_exterior_links", []).append({
                            "original_url": href, "verified_detail_url": evidence_url,
                            "lat": coords[0], "lon": coords[1],
                            "distance_km": distance_km(center, coords)})
                        if distance_km(center, coords) <= RADIUS_KM:
                            p = {"name": entry.get("name", ""),
                                 "lat": coords[0], "lon": coords[1],
                                 "key": identity(entry, coords), "source_url": href}
                            add_places(doc, [p])
                    tile["unresolved"] = remaining
                doc["unresolved_leaf_links"] = sum(
                    len(tile.get("unresolved", [])) for tile in
                    (doc.get("complete_tiles", {}).get(key) for key in
                     ("map_movement_v7_checkbox_on|" + "|".join(map(str, (n,e,0,t)))
                      for n in (-3.4,0.0,3.4) for e in (-3.4,0.0,3.4)
                      for t in ("psychotherapist","psychologist"))) if tile)
                if (doc.get("unresolved_leaf_links") == 0 and
                        doc.get("capped_leaf_tiles") == 0 and
                        not doc.get("pending") and
                        doc.get("status") == "coordinates_unresolved"):
                    doc["status"] = "verified_tile_feed"
                checkpoint.write_text(json.dumps(doc, indent=2))
        finally:
            browser.close()
    print("ADDITIONAL_GOOGLE_RESCUE", json.dumps({
        "fsa": code, "status": doc["status"],
        "prior_places": len(original),
        "new_places": len({p["key"] for p in doc["local_places"]} - original),
        "total_google_local_places": len(doc["local_places"]),
        "verified_new_probes": len(done),
        "source_failures": len(doc.get("additional_source_failures", {})),
        "unresolved_links": doc.get("unresolved_leaf_links"),
    }), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fsa", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--baseline", default="first-pass/google_all_ontario_498.csv")
    parser.add_argument("--seconds", type=int, default=1000)
    args = parser.parse_args()
    run(args.fsa, args.checkpoint, args.seed, args.baseline, args.seconds)
