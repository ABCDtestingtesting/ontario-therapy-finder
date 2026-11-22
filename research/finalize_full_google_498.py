"""Certify Google-only top-60 by bounding censored search results.

Google Maps returns observed *business locations*, not individual clinicians.
For a capped/incomplete area, the observed listing count is a LOWER BOUND and
residents per listing is therefore an UPPER BOUND. If 60 exact-feed areas have
higher ratios than an area's upper bound, that area's unfinished feed cannot
affect the top 60. All 498 areas remain in the transparent audit.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED = {'L6Z', 'L7A', 'L6X', 'L6R', 'N1T', 'N3S', 'P5N', 'N4W'}
SOURCE_STATUS = 'confirmed_observed_feed'


def as_bool(value):
    return str(value).lower() == 'true'


def source_complete(original):
    return original['status'] == SOURCE_STATUS and not as_bool(original['feed_capped']) and int(original['unlocated_links']) == 0


def combine(first_pass, recovery_root, output, native_root=None):
    with open(first_pass, newline='') as fh:
        originals = list(csv.DictReader(fh))
    if len(originals) != 498 or len({r['fsa'] for r in originals}) != 498:
        raise RuntimeError('Expected 498 distinct populated Ontario postal code areas')
    recovery = {}
    for path in Path(recovery_root).glob('**/[A-Z][0-9][A-Z].json'):
        item = json.loads(path.read_text())
        code = item['fsa']
        if code in recovery:
            raise RuntimeError('Duplicate Google tile recovery FSA: ' + code)
        recovery[code] = item

    native = {}
    if native_root:
        for path in Path(native_root).glob('**/native_evidence.json'):
            item = json.loads(path.read_text())
            code = item.get('fsa')
            if not code or code in native:
                raise RuntimeError('Duplicate or malformed independent native Google evidence')
            native[code] = item

    rows = []
    quality = Counter()
    for old in originals:
        code = old['fsa']
        source = recovery.get(code)
        pop = int(old['population_5km_estimate'])
        if pop <= 0:
            raise RuntimeError('Missing 2021 population near ' + code)
        previous = code in EXCLUDED or as_bool(old.get('previous_90_days'))
        baseline = int(old.get('google_observed_5km') or 0)
        observed_recovered = int(source.get('unique_observed_local_places') or 0) if source else 0
        independent = native.get(code)
        independent_observed = int(independent.get('unique_clinical_local_places') or 0) if independent else 0
        # Never add counts from distinct searches: overlaps cannot be assumed
        # disjoint without canonical Google place IDs. Max is a valid bound.
        lower = max(baseline, observed_recovered, independent_observed)
        # Distinct Google searches cannot be summed without place-level
        # deduplication. The maximum of two observed counts is a safe minimum.
        base_ok = source_complete(old)
        recovered_ok = bool(source and source.get('status') == 'verified_tile_feed'
                            and not source.get('pending')
                            and not source.get('capped_leaf_tiles')
                            and not source.get('unresolved_leaf_links'))
        native_ok = bool(independent
                         and independent.get('status') == 'grid_observed_complete'
                         and independent.get('process_returncode') == 0
                         and independent.get('raw_rows', 0) > 0
                         and not independent.get('bad_coordinates'))
        if base_ok:
            # Base count has a completed feed; the subsequent broader recovery
            # is not used to change its original comparable metric.
            count = baseline
            exact = True
            status = 'first_pass_complete'
        elif native_ok:
            # The independent small-cell Google Maps collector finished its
            # configured grid. This certifies the source observation protocol,
            # not an exhaustive count of licensed therapists.
            count = lower
            exact = True
            status = 'native_gridded_google_complete'
        elif recovered_ok:
            count = observed_recovered
            exact = True
            status = 'local_tiled_complete'
        else:
            count = lower
            exact = False
            status = 'censored_or_incomplete'
        if count < 0:
            raise RuntimeError('Negative Google observed places for ' + code)
        upper = pop / max(1, count)
        quality[status] += 1
        rows.append({
            'fsa': code,
            'population_5km_estimate_2021': pop,
            'google_observed_therapy_locations_lower_bound': lower,
            'google_therapy_locations_used_in_score': count,
            'residents_per_google_listing_or_upper_bound': round(upper, 2),
            'completed_source_feed': exact,
            'source_evidence_status': status,
            'excluded_last_90_days': previous,
            'latitude': old['latitude'],
            'longitude': old['longitude'],
            'google_first_pass_search_url': old['source_url'],
            'recovery_complete_tiles': len(source.get('complete_tiles', {})) if source else 0,
            'recovery_status': source.get('status') if source else '',
            'recovery_pending_queries': len(source.get('pending', [])) if source else None,
            'recovery_capped_base_queries': source.get('capped_leaf_tiles') if source else None,
            'recovery_unresolved_coords': source.get('unresolved_leaf_links') if source else None,
            'independent_google_grid_status': independent.get('status') if independent else '',
            'independent_google_raw_rows': independent.get('raw_rows') if independent else None,
            'independent_google_clinical_places': independent_observed,
            'independent_google_source_sha256': independent.get('raw_csv_sha256') if independent else None,
        })

    verified = sorted((r for r in rows if r['completed_source_feed']
                       and not r['excluded_last_90_days']),
                      key=lambda r: (-r['residents_per_google_listing_or_upper_bound'],
                                     r['google_therapy_locations_used_in_score'], r['fsa']))
    if len(verified) < 60:
        raise RuntimeError('Fewer than 60 completed Google source feeds')
    cutoff = verified[59]['residents_per_google_listing_or_upper_bound']
    contenders = sorted((r for r in rows if not r['completed_source_feed']
                         and not r['excluded_last_90_days']
                         and r['residents_per_google_listing_or_upper_bound'] >= cutoff),
                        key=lambda r: (-r['residents_per_google_listing_or_upper_bound'], r['fsa']))
    safe_to_exclude = [r for r in rows if not r['completed_source_feed']
                       and not r['excluded_last_90_days']
                       and r['residents_per_google_listing_or_upper_bound'] < cutoff]
    certified = not contenders
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)

    def write_csv(name, items, rank=False):
        fields = (['rank'] if rank else []) + list(rows[0].keys())
        with (out / name).open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for i, row in enumerate(items, start=1):
                writer.writerow({'rank': i, **row} if rank else row)

    write_csv('ontario_498_google_recovery_audit.csv', rows)
    write_csv('Ontario_Google_Top60_Completed_Feeds_Provisional.csv', verified[:60], rank=True)
    write_csv('Ontario_Google_Unresolved_Ranking_Contenders.csv', contenders)
    if certified:
        write_csv('Ontario_Google_Best_60_Across_498.csv', verified[:60], rank=True)

    report = {
        'total_ontario_fsa': len(rows),
        'first_pass_complete': quality['first_pass_complete'],
        'recovery_source_complete': quality['local_tiled_complete'],
        'independent_google_grid_source_complete': quality['native_gridded_google_complete'],
        'other_incomplete_google_sources': quality['censored_or_incomplete'],
        'dominated_incomplete_sources': len(safe_to_exclude),
        'potential_top_60_contenders_unresolved': len(contenders),
        'top_60_cutoff_residents_per_observed_google_location': cutoff,
        'google_60_certified_within_source_observation_model': certified,
        'certification_rule': 'All incomplete source upper bounds must fall strictly below 60th completed-source ratio',
        'note': 'A completed independent Google grid certifies the configured source scan, not exhaustive clinician coverage. Capped listings remain lower bounds. Geolocated business location counts, not therapists per clinic, are scored.',
        'psychology_today_used': False,
        '2021_population_source': 'Statistics Canada',
        'checked_at_utc': datetime.now(timezone.utc).isoformat()
    }
    (out / 'google_498_recovery_report.json').write_text(json.dumps(report, indent=2))
    print('ONTARIO_GOOGLE_498_COVERAGE', json.dumps(report), flush=True)
    if not certified:
        raise RuntimeError(f'{len(contenders)} incompletely observed areas could still enter the top 60; provisional ranked list and complete audit preserved')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('first_pass')
    parser.add_argument('recovery_root')
    parser.add_argument('output')
    parser.add_argument('--native-root', default=None)
    args = parser.parse_args()
    combine(args.first_pass, args.recovery_root, args.output, args.native_root)
