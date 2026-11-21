"""Merge every Ontario FSA's observed Google Maps evidence without treating missing as zero.

The earlier 498-row first pass remains the census baseline. Recoveries replace
capped and unresolved Google counts only when every required tile is complete.
No Psychology Today data enters the analysis.
"""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED = {'L6Z', 'L7A', 'L6X', 'L6R', 'N1T', 'N3S', 'P5N', 'N4W'}
SOURCE_STATUS = 'confirmed_observed_feed'


def truth(value):
    return str(value).lower() == 'true'


def combine(first_pass, recovery_root, output):
    with open(first_pass, newline='') as fh:
        originals = list(csv.DictReader(fh))
    if len(originals) != 498 or len({r['fsa'] for r in originals}) != 498:
        raise RuntimeError('Expected 498 distinct Ontario census population/FSA records')
    recovery = {}
    for path in Path(recovery_root).glob('**/[A-Z][0-9][A-Z].json'):
        item = json.loads(path.read_text())
        code = item['fsa']
        if code in recovery:
            raise RuntimeError('Duplicate Google tile recovery FSA: ' + code)
        recovery[code] = item
    results = []
    coverage = Counter()
    for old in originals:
        code = old['fsa']
        source = recovery.get(code)
        pop = int(old['population_5km_estimate'] or 0)
        original_complete = old['status'] == SOURCE_STATUS and not truth(old['feed_capped']) and old['unlocated_links'] == '0'
        if original_complete:
            status = 'google_first_pass_complete'
            count = int(old['google_observed_5km'])
            method = 'Single postal-specific Google Maps query with confirmed feed ending'
        elif source and source.get('status') == 'verified_tile_feed' and not source.get('pending') and source.get('capped_leaf_tiles') == 0 and source.get('unresolved_leaf_links') == 0:
            status = 'google_local_tiles_complete'
            count = int(source['unique_observed_local_places'])
            method = 'Two categories of overlapping geolocated Google Maps searches with adaptive subdivision'
        else:
            status = 'source_incomplete'
            count = None
            method = 'Needs more Google evidence'
        if pop <= 0:
            status = 'population_unavailable'
            count = None
        excluded = code in EXCLUDED
        ratio = round(pop / max(1, count), 2) if count is not None and pop > 0 else None
        coverage[status] += 1
        results.append({
            'fsa': code, 'population_5km_estimate_2021': pop,
            'google_observed_therapy_listings_5km': count,
            'residents_per_google_listing': ratio,
            'google_verification_status': status,
            'method': method, 'excluded_last_90_days': excluded,
            'latitude': old['latitude'], 'longitude': old['longitude'],
            'first_pass_google_source': old['source_url'],
            'recovery_google_queries': len(source.get('complete_tiles', {})) if source else 0,
            'recovery_unresolved_leaf_links': source.get('unresolved_leaf_links') if source else None,
            'recovery_capped_leaf_tiles': source.get('capped_leaf_tiles') if source else None
        })
    ranked = sorted((r for r in results if r['residents_per_google_listing'] is not None
                     and not r['excluded_last_90_days']),
                    key=lambda r: (-r['residents_per_google_listing'],
                                   r['google_observed_therapy_listings_5km'],
                                   -r['population_5km_estimate_2021'], r['fsa']))
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    with (out/'ontario_498_google_recovery_audit.csv').open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=results[0].keys())
        w.writeheader()
        w.writerows(results)
    complete = coverage['source_incomplete'] == 0 and coverage['population_unavailable'] == 0
    top = ranked[:60] if complete and len(ranked) >= 60 else []
    report = {
        'total_ontario_fsa': 498,
        'first_pass_confirmed': coverage['google_first_pass_complete'],
        'recovered_google_local_tiles': coverage['google_local_tiles_complete'],
        'source_incomplete': coverage['source_incomplete'],
        'population_unavailable': coverage['population_unavailable'],
        'recovery_checkpointed_fsas': len(recovery),
        'census_year': 2021,
        'psychology_today_used': False,
        'note': 'Google Maps public search results do not enumerate every licensed therapist; ratios count unique observed office/business listings. Baseline and recovery query coverage differ.',
        'top_60_certified_across_498': complete and len(top) == 60,
        'checked_at_utc': datetime.now(timezone.utc).isoformat()
    }
    (out/'google_498_recovery_report.json').write_text(json.dumps(report, indent=2))
    if top:
        with (out/'Ontario_Google_Best_60_Across_498.csv').open('w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['rank'] + list(results[0]))
            w.writeheader()
            for i, row in enumerate(top, 1):
                w.writerow({'rank': i, **row})
    print('ONTARIO_GOOGLE_498_COVERAGE', json.dumps(report), flush=True)
    if not complete:
        raise RuntimeError(f'Google evidence remains incomplete in {coverage["source_incomplete"]} areas; ranking is withheld')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('first_pass')
    p.add_argument('recovery_root')
    p.add_argument('output')
    args = p.parse_args()
    combine(args.first_pass, args.recovery_root, args.output)
