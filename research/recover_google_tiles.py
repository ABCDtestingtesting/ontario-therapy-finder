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
from finder.common import HumanVerificationRequired, SourceUnavailable
from research.scan_all_maps import distance_km, global_place_coordinates

RADIUS_KM = 5.0
SEARCHES = ('psychotherapist', 'psychologist')
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
    query = term  # Actual local coverage is proved by map movement and tile coordinates, not FSA text
    token = hashlib.sha256(f'{code}|{north:.3f}|{east:.3f}|{level}|{term}'.encode()).hexdigest()[:16]
    diagnostic = root / 'evidence' / code / token
    partial = False
    try:
        evidence = scan_one(
            context, query, lat, lon, diagnostic, timeout_seconds=55,
            max_scroll=22, zoom=16 if level else 14,
            force_map_refresh=True
        )
    except HumanVerificationRequired:
        # Restricted sources are still blocked. Do not interpret their visible
        # screen, challenge, or lack of listings as clinical search coverage.
        raise
    except SourceUnavailable:
        # scan_one persists source URL, exact query and any real place links
        # before raising when a Google feed lacks a verified ending. Save
        # those businesses as a LOWER BOUND and requeue the unfinished query.
        # Previously these real findings were silently lost.
        saved = diagnostic / 'search_evidence.json'
        if not saved.is_file():
            raise
        evidence = json.loads(saved.read_text())
        if (evidence.get('query') != query
            or evidence.get('geographic_refresh_verified') is not True
            or evidence.get('status') == 'verification_required'
            or not evidence.get('place_links')
            or not evidence.get('search_url', '').startswith('https://www.google.com/maps/search/')):
            raise
        partial = True
    if not partial and (not evidence.get('completed') or
                        evidence.get('completion_reason') not in COMPLETE):
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
        'term': term, 'source_url': evidence.get('geographic_refresh_url') or evidence['search_url'],
        'map_area_search_verified': evidence.get('geographic_refresh_verified') is True,
        'visible_links': len(links), 'capped': partial or len(links) >= 120,
        'reason': evidence.get('completion_reason'), 'places': list(inside.values()),
        'unresolved': unresolved, 'status': 'observed_partial' if partial else 'observed',
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
    # Never reuse old broad FSA-text searches as evidence of geographically
    # scoped Google Maps results. All 18 base queries must be repeated with
    # the actual visible map's 'update results when map moves' feature on.
    return 'map_movement_v6_category_only|' + '|'.join(map(str, task))



RECENTLY_SCREENED = {'L6Z', 'L7A', 'L6X', 'L6R', 'N1T', 'N3S', 'P5N', 'N4W'}


def priority_unresolved_fsas(first_pass):
    """Identify areas that can still beat the current 60th verified ratio.

    With a capped Google feed, observed competitors are a LOWER BOUND.
    Thus population/max(1,observed_competitors) is an UPPER BOUND on the
    actual residents-per-listing ratio. Areas whose upper bound is strictly
    below the 60th completed area's observed ratio cannot improve its rank
    under this scoring model. Keep the full 498-row audit intact.
    """
    if len(first_pass) != 498 or len({r['fsa'] for r in first_pass}) != 498:
        raise RuntimeError('Expected exactly 498 distinct Ontario FSAs')
    def recent(row):
        return row['fsa'] in RECENTLY_SCREENED or str(row.get('previous_90_days', '')).lower() == 'true'
    def score_upper(row):
        people = int(float(row['population_5km_estimate']))
        competitors = int(float(row.get('google_observed_5km') or 0))
        if people <= 0 or competitors < 0:
            raise RuntimeError('Invalid population or Google observation for ' + row['fsa'])
        return people / max(1, competitors)
    base = sorted((score_upper(row) for row in first_pass
                   if row['status'] == 'confirmed_observed_feed' and not recent(row)),
                  reverse=True)
    if len(base) < 60:
        raise RuntimeError('Cannot narrow research before 60 completed baseline areas exist')
    cutoff = base[59]
    unfinished = [row for row in first_pass
                  if row['status'] != 'confirmed_observed_feed' and not recent(row)]
    priority = {row['fsa'] for row in unfinished if score_upper(row) >= cutoff}
    excluded = {row['fsa'] for row in unfinished if score_upper(row) < cutoff}
    if len(priority | excluded) != len(unfinished) or priority & excluded:
        raise RuntimeError('Google research screening lost unresolved FSAs')
    return priority, excluded, cutoff


def is_rank_dominated(area, observed_places):
    """Prove that this area cannot enter the Google-only top 60.

    Both the original search count and deduplicated tiled count are lower
    bounds, so their maximum remains a valid lower bound without assuming
    different searches contain disjoint results. The inequality is strict
    because ties must remain possible contenders.
    """
    if not {'ranking_cutoff', 'population_5km_estimate', 'baseline_observed_5km'} <= area.keys():
        return False
    people = int(area['population_5km_estimate'])
    cutoff = float(area['ranking_cutoff'])
    baseline = int(area['baseline_observed_5km'])
    if people <= 0 or cutoff <= 0 or baseline < 0:
        raise RuntimeError('Bad population / observed Google bound for ' + area['fsa'])
    return people / max(1, baseline, observed_places) < cutoff


def run_area(context, area, folder, max_seconds):
    """Finish a bounded 18-search local coverage plan, reusing legacy evidence.

    Older checkpoints may contain thousands of queued recursive descendants.
    Those searches were not bounded and most repeats returned the same 120
    Google listings. Keep completed evidence, replace that pending work with
    a fixed 3x3 by two-query plan, and label capped searches honestly.
    """
    code = area['fsa']
    centre = (area['lat'], area['lon'])
    record_path = folder / f'{code}.json'
    if record_path.exists():
        doc = json.loads(record_path.read_text())
        if doc.get('fsa') != code:
            raise RuntimeError(f'Checkpoint FSA does not match {code}')
    else:
        doc = {'fsa': code, 'center': centre, 'population_2021_fsa': area['population_2021'],
               'status': 'in_progress', 'complete_tiles': {}, 'attempts': 0}
    doc.setdefault('complete_tiles', {})
    doc.setdefault('attempts', 0)
    doc.setdefault('tile_failures', {})
    required = [list(task) for task in tile_tasks()]
    required_keys = {task_key(task) for task in required}
    if len(required) != 18 or len(required_keys) != 18:
        raise RuntimeError('Bounded Google query plan must contain 18 unique tiles')
    # Crucial: never restore the exponential pending queue from version 1.
    doc['pending'] = [task for task in required
                      if task_key(task) not in doc['complete_tiles']
                      or doc['complete_tiles'][task_key(task)].get('status') == 'observed_partial']
    doc['recovery_plan'] = 'fixed_18_map_movement_v6_categories_geographically_scoped'
    doc['discarded_recursive_pending'] = True
    record_path.write_text(json.dumps(doc, indent=2))
    started = time.monotonic()
    failed_this_run = set()
    access_restricted = False
    # Keep all legacy completed evidence; no new Google calls are necessary
    # once known local places already disqualify a censored source.
    def observed_count():
        return len({p['key'] for e in doc['complete_tiles'].values()
                    for p in e.get('places', [])})
    early_dominated = is_rank_dominated(area, observed_count())
    while doc['pending'] and not early_dominated and time.monotonic() - started < max_seconds:
        task = tuple(doc['pending'][0])
        key = task_key(task)
        try:
            evidence = scan_tile(context, code, centre, *task, folder)
            doc['complete_tiles'][key] = evidence
            doc['attempts'] += 1
            doc['pending'].pop(0)
            doc['tile_failures'].pop(key, None)
            early_dominated = is_rank_dominated(area, observed_count())
        except HumanVerificationRequired as exc:
            doc['tile_failures'][key] = {'error': str(exc),
                                         'type': 'access_restricted',
                                         'at': datetime.now(timezone.utc).isoformat()}
            access_restricted = True
            doc['last_error'] = str(exc)
            break
        except Exception as exc:
            # A broken tile cannot block the other 17 indefinitely. Try it on
            # the next recovery run, not in a busy retry loop.
            doc['tile_failures'][key] = {'error': type(exc).__name__ + ': ' + str(exc),
                                         'type': 'source_incomplete',
                                         'at': datetime.now(timezone.utc).isoformat()}
            failed_this_run.add(key)
            doc['attempts'] += 1
            doc['pending'].pop(0)
        finally:
            record_path.write_text(json.dumps(doc, indent=2))
    # Every missing base query stays pending for the next run. Legacy completed
    # results stay as lower-bound evidence; changed query keys require fresh local searches.
    doc['pending'] = [task for task in required
                      if task_key(task) not in doc['complete_tiles']
                      or doc['complete_tiles'][task_key(task)].get('status') == 'observed_partial']
    # Detail-page categories from later verified lookups are part of the
    # durable source evidence. A resumed tile search must not erase them.
    previously_classified = {
        p['key']: p for p in doc.get('local_places', [])
        if p.get('google_business_category')
    }
    merged = {}
    for entry in doc['complete_tiles'].values():
        for p in entry.get('places', []):
            merged[p['key']] = p
            old_detail = previously_classified.get(p['key'])
            if old_detail:
                for field in ('google_business_category', 'google_category_checked_at',
                              'google_category_evidence_url'):
                    if old_detail.get(field):
                        merged[p['key']][field] = old_detail[field]
    base = [doc['complete_tiles'][key] for key in required_keys
            if key in doc['complete_tiles']]
    capped = sum(bool(entry.get('capped')) for entry in base)
    unresolved = {p['url'] for entry in base for p in entry.get('unresolved', [])
                  if p.get('url')}
    doc['unique_observed_local_places'] = len(merged)
    doc['local_places'] = list(merged.values())
    doc['capped_leaf_tiles'] = capped
    doc['unresolved_leaf_links'] = len(unresolved)
    doc['completed_coverage_tiles'] = len(base)
    doc['total_coverage_tiles'] = len(required)
    doc['source_caps_present'] = capped > 0
    doc['failed_tiles_this_run'] = len(failed_this_run)
    doc['rank_dominated_by_verified_cutoff'] = early_dominated
    if early_dominated:
        doc['status'] = 'rank_dominated_early'
    elif access_restricted:
        doc['status'] = 'access_restricted'
    elif doc['pending']:
        doc['status'] = 'coverage_incomplete'
    elif unresolved:
        doc['status'] = 'coordinates_unresolved'
    elif capped:
        # This is an OBSERVED LOWER BOUND of Google business listings. It is
        # not an exhaustive count or an absence-of-therapists certification.
        doc['status'] = 'observed_capped'
    else:
        doc['status'] = 'verified_tile_feed'
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
    priority, dominated, cutoff = priority_unresolved_fsas(first_pass)
    print('GOOGLE_RANKING_PRIORITY', json.dumps({
        'candidates_to_recover': len(priority), 'already_dominated': len(dominated),
        'verified_60th_ratio': cutoff, 'total_fsa': len(first_pass),
        'screening_proof': 'incomplete count is lower bound, ratio is upper bound'
    }), flush=True)
    first_pass_by_fsa = {row['fsa']: row for row in first_pass}
    # Keep ORIGINAL 241-area shard assignment so resumed artifacts never
    # duplicate the same FSA in two different shard files.
    targets = [a for i, a in enumerate(targets)
               if i % args.shards == args.shard and a['fsa'] in priority]
    root = Path(args.out) / f'shard-{args.shard}'
    root.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(
            str(root / 'profile'), headless=True,
            viewport={'width': 1400, 'height': 960}, locale='en-CA'
        )
        try:
            for area in targets:
                old = first_pass_by_fsa[area['fsa']]
                enriched = dict(area, ranking_cutoff=cutoff,
                    population_5km_estimate=int(old['population_5km_estimate']),
                    baseline_observed_5km=int(float(old.get('google_observed_5km') or 0)))
                r = run_area(ctx, enriched, root, args.seconds_per_area)
                print('TILE_FSA_RESULT', json.dumps({
                    'fsa': r['fsa'], 'status': r['status'],
                    'places': r['unique_observed_local_places'],
                    'pending': len(r['pending']), 'attempts': r['attempts'],
                    'capped_leaf': r['capped_leaf_tiles'],
                    'unresolved_leaf': r['unresolved_leaf_links'],
                    'rank_dominated': r['rank_dominated_by_verified_cutoff']
                }), flush=True)
                if r['status'] == 'access_restricted':
                    print('Google access restricted; preserving all evidence, ending shard', flush=True)
                    break
        finally:
            ctx.close()
    print('TILE_SHARD_FINISHED', args.shard, len(targets), flush=True)


if __name__ == '__main__':
    main()
