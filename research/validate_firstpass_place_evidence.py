"""Recover auditable clinical-listing lower bounds from original 498 Ontario
Google Maps *place-level* source artifacts. Never convert an aggregate
keyword-hit count to a therapist count, nor an empty result to verified absence.
The 44 original shards are from workflow runs 44949320059 and 44949323771.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

from research.finalize_full_google_498 import clinical_title_classification
from research.scan_all_maps import distance_km

EXPECTED_SHARDS = 44
EXPECTED_FSAS = 498
RADIUS_KM = 5.0


def parse_sources(source_root: Path, baseline_path: Path):
    with baseline_path.open(newline='', encoding='utf8') as fh:
        baseline = list(csv.DictReader(fh))
    if len(baseline) != EXPECTED_FSAS or len({r['fsa'] for r in baseline}) != EXPECTED_FSAS:
        raise RuntimeError('Expected exactly 498 unique audited Ontario census FSAs')
    base = {r['fsa']: r for r in baseline}
    paths = sorted(source_root.glob('**/results.json'))
    if len(paths) != EXPECTED_SHARDS:
        raise RuntimeError(f'Missing original Ontario Google shards: {len(paths)}/{EXPECTED_SHARDS}')
    output = {}
    details = {}
    all_places = {}
    for path in paths:
        raw = path.read_bytes()
        data = json.loads(raw)
        rows = data.get('rows')
        if not isinstance(rows, list) or not rows:
            raise RuntimeError(f'Empty or invalid Google source shard {path}')
        shard_sha = hashlib.sha256(raw).hexdigest()
        for record in rows:
            code = record.get('fsa')
            if code not in base or code in output:
                raise RuntimeError(f'Duplicate or foreign FSA in original Google source: {code}')
            anchor = base[code]
            center = tuple(float(v) for v in record.get('center', []))
            expected = (float(anchor['latitude']), float(anchor['longitude']))
            if len(center) != 2 or max(abs(center[i]-expected[i]) for i in (0,1)) > 0.00001:
                raise RuntimeError(f'Original Google FSA centre mismatch: {code}')
            query = f'psychotherapist near {code} Ontario Canada'
            if record.get('status') == 'incomplete':
                if record.get('search_query') or record.get('locations') or record.get('local_count') not in (None, 0):
                    raise RuntimeError(f'Incomplete Google source contains unverified results: {code}')
            elif record.get('search_query') != query:
                raise RuntimeError(f'Original Google search query mismatch: {code}')
            locations = record.get('locations') or []
            if not isinstance(locations, list):
                raise RuntimeError(f'Unparseable original Google locations: {code}')
            expected_count = record.get('local_count')
            if expected_count is not None and int(expected_count) != len(locations):
                raise RuntimeError(f'Original Google location-count disagreement: {code}')
            if record.get('status') not in ('observed','unresolved','incomplete'):
                raise RuntimeError(f'Unexpected source status for {code}')
            unique = set()
            clinical, ambiguous, nonclinical = [], 0, 0
            all_local = []
            for place in locations:
                name = str(place.get('name') or '').strip()
                url = str(place.get('url') or '')
                if not name or not url.startswith('https://www.google.com/maps/place/'):
                    raise RuntimeError(f'Missing real Google business evidence: {code}')
                xy = (float(place['lat']), float(place['lon']))
                if not (-90<=xy[0]<=90 and -180<=xy[1]<=180) or distance_km(center, xy)>RADIUS_KM+0.001:
                    raise RuntimeError(f'Google business outside verified 5-km FSA: {code}')
                ident = (name.casefold(), round(xy[0],4), round(xy[1],4))
                if ident in unique:
                    raise RuntimeError(f'Duplicate location in original FSA source: {code}')
                unique.add(ident)
                kind = clinical_title_classification({'name':name, 'lat':xy[0],
                    'lon':xy[1], 'source_url':url})
                all_local.append({'name':name,'lat':xy[0],'lon':xy[1],
                    'source_url':url,'observed_title_classification':kind,
                    'key':name.casefold()+':'+str(round(xy[0],5))+':'+str(round(xy[1],5))})
                if kind == 'clinical':
                    clinical.append({'name':name,'lat':xy[0],'lon':xy[1],
                        'google_place_url':url})
                elif kind == 'nonclinical':
                    nonclinical += 1
                else:
                    ambiguous += 1
            output[code] = {
                'fsa':code,
                'original_source_status':record['status'],
                'original_google_located_businesses':len(locations),
                'firstpass_clinical_title_lower_bound':len(clinical),
                'firstpass_nonclinical_titles':nonclinical,
                'firstpass_ambiguous_titles':ambiguous,
                'firstpass_unlocated_links':int(record.get('unlocated_count') or 0),
                'firstpass_capped':str(record.get('feed_capped',False)).lower() == 'true',
                'firstpass_source_shard_sha256':shard_sha,
                'firstpass_search_url':record.get('search_url',''),
                'clinician_absence_verified':False,
            }
            details[code] = clinical
            all_places[code] = all_local
    if set(output) != set(base):
        raise RuntimeError(f'Original Google evidence cannot be reconciled to 498 FSAs: {len(output)}')
    for code in output:
        if output[code]['original_google_located_businesses'] != (
            output[code]['firstpass_clinical_title_lower_bound']
            + output[code]['firstpass_nonclinical_titles']
            + output[code]['firstpass_ambiguous_titles']):
            raise RuntimeError('Original business category partition failed for '+code)
    return output, details, all_places


def run(source_root: Path, baseline_path: Path, out_dir: Path):
    rows, details, all_places = parse_sources(source_root,baseline_path)
    out_dir.mkdir(parents=True,exist_ok=True)
    with (out_dir/'Ontario_498_Firstpass_Verified_Clinical_Lower_Bounds.csv').open(
        'w',newline='',encoding='utf8') as fh:
        writer = csv.DictWriter(fh,fieldnames=list(next(iter(rows.values()))))
        writer.writeheader()
        for code in sorted(rows): writer.writerow(rows[code])
    (out_dir/'Ontario_498_Firstpass_Verified_Clinical_Evidence.json').write_text(
        json.dumps({'method':'original geolocated Google Maps place titles, not keyword counts',
          'source_runs':[44949320059,44949323771],
          'no_claim_of_absence':True,'clinical_places_by_fsa':details},indent=2))
    (out_dir/'Ontario_498_All_Google_Businesses_With_Uncertain_Categories.json').write_text(
        json.dumps({'source_runs':[44949320059,44949323771],
          'source_type':'geographically verified Google Maps place listings',
          'all_places_by_fsa':all_places},indent=2))
    report = {
      'fsa_count':len(rows),
      'google_source_shards':EXPECTED_SHARDS,
      'geolocated_google_businesses':sum(x['original_google_located_businesses'] for x in rows.values()),
      'title_confirmed_clinical_lower_bound':sum(x['firstpass_clinical_title_lower_bound'] for x in rows.values()),
      'ambiguous_business_titles':sum(x['firstpass_ambiguous_titles'] for x in rows.values()),
      'clinically_positive_fsa_count':sum(x['firstpass_clinical_title_lower_bound']>0 for x in rows.values()),
      'provider_absence_certified':False,
    }
    (out_dir/'Ontario_498_Firstpass_Evidence_Recovery_Report.json').write_text(
        json.dumps(report,indent=2))
    print('GOOGLE_FIRSTPASS_CLINICAL_LOWER_BOUND_RECOVERY',json.dumps(report),flush=True)
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    run(a.sources,a.baseline,a.out)
