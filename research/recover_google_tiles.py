"""Recover censored Ontario Google Maps competition using overlapping local tiles.

Every output is a source observation, not a claim that Google enumerates every
provider. Failed/challenged tiles remain explicitly incomplete and resumable.
Does not use Psychology Today.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
from finder.google_browser import scan_one, resolve_place_coordinates
from finder.common import HumanVerificationRequired
from research.scan_all_maps import distance_km, global_place_coordinates

RADIUS_KM = 5.0
SEARCHES = ('psychotherapist', 'counselling therapy')
# 3.4 km grid supplies 9 overlapping centres; capped tiles subdivide.
BASE_OFFSETS_KM = (-3.4, 0.0, 3.4)
SUB_OFFSETS_KM = (-1.15, 0.0, 1.15)
MAX_LEVEL = 2
COMPLETE = {'visible_end_of_list', 'explicit_no_results', 'single_place_panel'}


def tile_coords(center, north_km, east_km):
    lat, lon = center
    new_lat = lat + north_km / 111.1
    new_lon = lon + east_km / (111.1 * max(0.2, math.cos(math.radians(lat))))
    return round(new_lat, 6), round(new_lon, 6)


def identity(link, xy):
    import re
    url = link.get('url', '')
    match = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', url, re.I)
    if match:
        return 'google:' + match.group(1).lower()
    label = (link.get('name') or '').casefold().strip()
    return label + ':' + str(round(xy[0], 5)) + ':' + str(round(xy[1], 5))


def scan_tile(context, code, center, north, east, level, term, root):
    lat, lon = tile_coords(center, north, east)
    # Google may surface off-centre places even for a centred search. Filter by
    # actual PLACE coordinates after collection, never by map-viewport coords.
    query = term
    token = hashlib.sha256(f'{code}|{north:.3f}|{east:.3f}|{level}|{term}'.encode()).hexdigest()[:16]
    diagnostic = root / 'evidence' / code / token
    evidence = scan_one(
        context, query, lat, lon, diagnostic, timeout_seconds=55,
        max_scroll=22, zoom=17 if level else 15
    )
    if not evidence.get('completed') or evidence.get('completion_reason') not in COMPLETE:
        raise RuntimeError('No evidenced Google Maps end-of-feed marker')
    links = evidence.get('place_links', [])
    inside, unresolved = {}, []
    for link in links:
        xy = link.get('coordinates') or global_place_coordinates(link.get('url', ''))
        if xy is None:
            try:
                xy, proven = resolve_place_coordinates(context, link['url'], timeout_ms=6500)
            except Exception:
                xy = None
        if xy is None:
            unresolved.append({'url': link['url'], 'name': link.get('name')})
            continue
        if distance_km(center, xy) <= RADIUS_KM:
            key = identity(link, xy)
            inside[key] = {'name': link.get('name') or 'Unknown', 'lat': xy[0],
                           'lon': xy[1], 'source_url': link.get('url'), 'key': key}
    return {
        'code': code, 'north_km': north, 'east_km': east, 'level': level,
        'term': term, 'source_url': evidence['search_url'],
        'visible_links': len(links), 'capped': len(links) >= 120,
        'reason': evidence['completion_reason'], 'places': list(inside.values()),
        'unresolved': unresolved, 'status': 'observed',
        'observed_at': datetime.now(timezone.utc).isoformat(),
    }


def tile_tasks():
    # Cover the 5 km circle with 9 broad searches and finer probes only if
    # the source feed caps or a listing's location cannot be established.
    for north in BASE_OFFSETS_KM:
        for east in BASE_OFFSETS_KM:
            for term in SEARCHES:
                yield (round(north, 3), round(east, 3), 0, term)


def children(task):
    north, east, level, term = task
    step = 1.15 / (2 ** level)
    for dn in (-step, 0.0, step):
        for de in (-step, 0.0, step):
            yield (round(north + dn, 3), round(east + de, 3), level + 1, term)


def task_key(task):
    return '|'.join(map(str, task))


def run_area(context, area, folder, max_seconds):
    code = area['fsa']
    centre = (area['lat'], area['lon'])
    record_path = folder / f'{code}.json'
    if record_path.exists():
        doc = json.loads(record_path.read_text())
        if doc.get('status') == 'verified_tile_feed':
            return doc
    else:
        doc = {'fsa': code, 'center': centre, 'population_2021_fsa': area['population_2021'],
               'status': 'in_progress', 'complete_tiles': {}, 'pending': [], 'attempts': 0}
    if not doc['pending']:
        if not doc['complete_tiles']:
            doc['pending'] = [list(x) for x in tile_tasks()]
    started = time.monotonic()
    while doc['pending'] and time.monotonic() - started < max_seconds:
        task = tuple(doc['pending'][0])
        key = task_key(task)
        if key in doc['complete_tiles']:
            doc['pending'].pop(0)
            continue
        try:
            evidence = scan_tile(context, code, centre, *task, folder)
            doc['complete_tiles'][key] = evidence
            doc['attempts'] += 1
            doc['pending'].pop(0)
            if (evidence['capped'] or evidence['unresolved']) and task[2] < MAX_LEVEL:
                doc['pending'].extend(list(x) for x in children(task))
        except HumanVerificationRequired as exc:
            doc['status'] = 'access_restricted'
            doc['last_error'] = str(exc)
            break
        except Exception as exc:
            # Never turn failed queries into zero competitors.
            doc['status'] = 'needs_retry'
            doc['last_error'] = type(exc).__name__ + ': ' + str(exc)
            doc['attempts'] += 1
            break
        finally:
            record_path.write_text(json.dumps(doc, indent=2))
    merged = {}
    capped_final = 0
    unresolved_final = 0
    for entry in doc['complete_tiles'].values():
        # Intermediate coarse tiles are retained for provenance. Count a capped
        # leaf as unresolved until its finer descendants complete.
        if entry['level'] >= MAX_LEVEL and entry['capped']:
            capped_final += 1
        if entry['level'] >= MAX_LEVEL:
            unresolved_final += len(entry['unresolved'])
        for p in entry['places']:
            merged[p['key']] = p
    doc['unique_observed_local_places'] = len(merged)
    doc['local_places'] = list(merged.values())
    doc['capped_leaf_tiles'] = capped_final
    doc['unresolved_leaf_links'] = unresolved_final
    if not doc['pending'] and capped_final == 0 and unresolved_final == 0:
        doc['status'] = 'verified_tile_feed'
    elif doc.get('status') not in ('access_restricted', 'needs_retry'):
        doc['status'] = 'coverage_incomplete'
    doc['updated_at'] = datetime.now(timezone.utc).isoformat()
    record_path.write_text(json.dumps(doc, indent=2))
    return doc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--shard', type=int, required=True)
    parser.add_argument('--shards', type=int, default=48)
    parser.add_argument('--audit', default='first-pass/google_all_ontario_498.csv')
    parser.add_argument('--out', default='recovery-output')
    parser.add_argument('--seconds-per-area', type=int, default=1050)
    args = parser.parse_args()

    full_pool = json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())['areas']
    with open(args.audit, newline='') as handle:
        first_pass = list(csv.DictReader(handle))
    if len(full_pool) != 498 or len(first_pass) != 498:
        raise RuntimeError('Expected 498 official populated Ontario FSA records')
    selected = {r['fsa'] for r in first_pass if r['status'] != 'confirmed_observed_feed'}
    targets = [a for a in full_pool if a['fsa'] in selected]
    if len(targets) != 241:
        raise RuntimeError(f'Unexpected unresolved source set: {len(targets)}')
    targets = [a for i, a in enumerate(targets) if i % args.shards == args.shard]
    root = Path(args.out) / f'shard-{args.shard:02d}'
    root.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(
            str(root / 'profile'), headless=True,
            viewport={'width': 1400, 'height': 960}, locale='en-CA'
        )
        try:
            for area in targets:
                r = run_area(ctx, area, root, args.seconds_per_area)
                print('TILE_FSA_RESULT', json.dumps({
                    'fsa': r['fsa'], 'status': r['status'],
                    'places': r['unique_observed_local_places'],
                    'pending': len(r['pending']), 'attempts': r['attempts'],
                    'capped_leaf': r['capped_leaf_tiles'],
                    'unresolved_leaf': r['unresolved_leaf_links']
                }), flush=True)
                if r['status'] == 'access_restricted':
                    print('Google access restricted; preserving all evidence, ending shard', flush=True)
                    break
        finally:
            ctx.close()
    print('TILE_SHARD_FINISHED', args.shard, len(targets), flush=True)


if __name__ == '__main__':
    main()
