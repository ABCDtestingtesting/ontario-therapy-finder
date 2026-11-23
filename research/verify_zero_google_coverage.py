"""Independently reobserve all 53 nominal zero-count Ontario Google FSAs.

The earlier "confirmed_observed_feed" zero came from one exact postal-code
search query. It cannot establish zero physical therapy practices. This
independent, fixed 3x3 grid uses THREE different category queries, verifies
the Google map centre for every tile, and saves every unique business's
actual place coordinate inside the original 5 km study circle.

A challenge, failed request, incomplete/capped results, or unknown clinical
business type is never interpreted as proof that a region has no providers.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

from finder.common import HumanVerificationRequired, SourceUnavailable
from finder import google_browser
from research.google_measured_recenter_runner import refresh
from research.recover_google_tiles import scan_tile, tile_coords, RADIUS_KM
from research.scan_all_maps import distance_km
from research.finalize_full_google_498 import clinical_title_classification

SEARCH_TERMS = ('counselling', 'psychotherapy', 'mental health clinic')
OFFSETS = (-3.4, 0.0, 3.4)
EXPECTED_KEYS = {
    f'independent_3term_map_grid_v1|{north}|{east}|{term}'
    for north in OFFSETS for east in OFFSETS for term in SEARCH_TERMS
}


def validate_source(code, csvpath):
    with csvpath.open(newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != 498 or len({r['fsa'] for r in rows}) != 498:
        raise RuntimeError('Source must be exactly 498 unique Ontario FSAs')
    matches = [r for r in rows if r['fsa'] == code]
    if len(matches) != 1 or float(matches[0]['google_therapy_locations_used_in_score']) != 0:
        raise RuntimeError('Crosscheck only previously zero-count Ontario FSAs')
    if str(matches[0]['excluded_last_90_days']).lower() == 'true':
        raise RuntimeError('Excluded recently researched source')
    areas = json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())['areas']
    ref = [x for x in areas if x['fsa'] == code]
    if len(ref) != 1:
        raise RuntimeError('Ontario official FSA centroid missing')
    row = matches[0]
    centre = (float(row['latitude']), float(row['longitude']))
    if max(abs(a-b) for a,b in zip(centre,(ref[0]['lat'],ref[0]['lon']))) > 0.00001:
        raise RuntimeError('2021 census geographic centroid has changed')
    return centre


def summarize(doc):
    values = {p['key']:p for tile in doc.get('observations',{}).values()
              for p in tile.get('places',[]) if p.get('key')}
    doc['unique_local_google_businesses'] = len(values)
    doc['local_google_places'] = list(values.values())
    doc['clinical_title_confirmed'] = sum(
        clinical_title_classification(x) == 'clinical' for x in values.values())
    doc['nonclinical_title_confirmed'] = sum(
        clinical_title_classification(x) == 'nonclinical' for x in values.values())
    doc['ambiguous_businesses'] = sum(
        clinical_title_classification(x) == 'ambiguous' for x in values.values())
    incompletes = [
        key for key in EXPECTED_KEYS
        if key not in doc.get('observations',{})
        or doc['observations'][key].get('capped')
        or doc['observations'][key].get('unresolved')
        or doc['observations'][key].get('status') != 'observed'
        or doc['observations'][key].get('map_area_search_verified') is not True
    ]
    doc['unverified_searches'] = sorted(incompletes)
    doc['status'] = ('all_27_independent_google_feeds_observed'
                     if not incompletes else 'crosscheck_incomplete')
    doc['updated_at_utc'] = datetime.now(timezone.utc).isoformat()
    return doc


def run(code, baseline, out, budget):
    if not (60 <= budget <= 2500):
        raise RuntimeError('Invalid bounded source collection time')
    centre = validate_source(code,baseline)
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.is_file():
        doc = json.loads(out.read_text())
        if doc.get('fsa')!=code or tuple(doc.get('center',()))!=centre:
            raise RuntimeError('Historical checkpoint FSA identity changed')
    else:
        doc={'fsa':code,'center':centre,'radius_km':RADIUS_KM,
             'search_terms':SEARCH_TERMS,'observations':{},'failures':{},
             'status':'in_progress','data_model_version':'independent_3term_map_grid_v1'}
    started=time.monotonic()
    # Reuse the already inspected map movement control and measurable recenter
    # check instead of relying on Google's URL query words to prove geography.
    google_browser._refresh_map_area_results = refresh
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(
            str(out.parent/'firefox_profile'),headless=True,
            viewport={'width':1400,'height':960},locale='en-CA')
        try:
            for north in OFFSETS:
                for east in OFFSETS:
                    for term in SEARCH_TERMS:
                        key=f'independent_3term_map_grid_v1|{north}|{east}|{term}'
                        past=doc['observations'].get(key)
                        if past and (not past.get('capped') and not past.get('unresolved')
                                     and past.get('status')=='observed'
                                     and past.get('map_area_search_verified') is True):
                            continue
                        if time.monotonic()-started >= budget:
                            summarize(doc)
                            out.write_text(json.dumps(doc,indent=2))
                            print('GOOGLE_ZERO_CROSSCHECK_BUDGET_EXHAUSTED',code,flush=True)
                            return doc
                        try:
                            tile=scan_tile(ctx,code,centre,north,east,0,term,out.parent)
                            for place in tile.get('places',[]):
                                p=(float(place['lat']),float(place['lon']))
                                if distance_km(centre,p)>RADIUS_KM:
                                    raise RuntimeError('Google competitor outside FSA study radius')
                            if past:
                                doc.setdefault('superseded_observations',{}).setdefault(key,[]).append(past)
                                previous={p['key']:p for p in past.get('places',[])}
                                previous.update({p['key']:p for p in tile.get('places',[])})
                                tile['places']=list(previous.values())
                            doc['observations'][key]=tile
                            doc['failures'].pop(key,None)
                        except (HumanVerificationRequired,SourceUnavailable) as exc:
                            doc['failures'][key]={
                                'type':type(exc).__name__,
                                'message':str(exc)[:350],
                                'updated_at_utc':datetime.now(timezone.utc).isoformat()}
                        except Exception as exc:
                            doc['failures'][key]={
                                'type':type(exc).__name__,
                                'message':str(exc)[:350],
                                'updated_at_utc':datetime.now(timezone.utc).isoformat()}
                        finally:
                            summarize(doc)
                            out.write_text(json.dumps(doc,indent=2))
        finally:
            ctx.close()
    result=summarize(doc)
    out.write_text(json.dumps(result,indent=2))
    print('INDEPENDENT_ZERO_FSA_CROSSCHECK', json.dumps({
        'fsa':code,'status':result['status'],
        'completed_or_partially_observed':len(result['observations']),
        'unverified_queries':len(result['unverified_searches']),
        'unique_local_google_businesses':result['unique_local_google_businesses'],
        'clinical_title_confirmed':result['clinical_title_confirmed'],
        'ambiguous_businesses':result['ambiguous_businesses'],
        'failure_count':len(result['failures'])}),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--fsa',required=True)
    p.add_argument('--baseline',type=Path,default=Path('first-pass/ontario_498_google_recovery_audit.csv'))
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=1650)
    a=p.parse_args()
    final=run(a.fsa,a.baseline,a.out,a.seconds)
    if final['status'] != 'all_27_independent_google_feeds_observed':
        raise SystemExit('Preserved incomplete Google evidence for further source review')
