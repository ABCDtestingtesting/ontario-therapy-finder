"""Prepare the remaining independently eligible Google-only Ontario FSAs.

Uses the immutable first-pass artifacts from GitHub run 44952655975.
Never converts an incomplete Google source record into an eligible candidate.
"""
import csv
import json
import sys
from pathlib import Path

def main(source_dir='research-source', output_path='research/additional_candidates_94.json'):
    source = Path(source_dir)
    with (source / 'preliminary_top_180.json').open() as f:
        original = json.load(f)
    original_codes = {item['fsa'] for item in original['candidates']}
    with (source / 'google_all_ontario_498.csv').open(newline='') as f:
        all_rows = list(csv.DictReader(f))
    if len(all_rows) != 498 or len(original_codes) != 180:
        raise RuntimeError('Unexpected source universe or first candidate shortlist size')
    extras = []
    for row in all_rows:
        code = row['fsa']
        if row['rank_eligible'].lower() != 'true' or code in original_codes:
            continue
        if row['status'] != 'confirmed_observed_feed' or row['unlocated_links'] != '0':
            raise RuntimeError(f'Candidate {code} lacks verified first-pass Google locations')
        extras.append({
            'fsa': code,
            'latitude': float(row['latitude']),
            'longitude': float(row['longitude']),
            'population_5km_estimate': int(row['population_5km_estimate']),
            'population_2021_fsa': int(row['population_2021_fsa']),
            'first_pass_weighted_score': float(row['residents_per_observed_google_listing']),
        })
    extras.sort(key=lambda row: (-row['first_pass_weighted_score'], row['fsa']))
    codes = [item['fsa'] for item in extras]
    if len(extras) != 94 or len(set(codes)) != 94:
        raise RuntimeError(f'Expected 94 previously unsearched eligible candidates, got {len(extras)}')
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        'candidate_count': len(extras),
        'source_fsas': 498,
        'ranking': 'Additional verified-first-pass Google candidates; independent two-search audit required',
        'candidates': extras
    }, indent=2))
    print('ADDITIONAL_ELIGIBLE_GOOGLE_CANDIDATES', len(extras), flush=True)

if __name__ == '__main__':
    main(*sys.argv[1:])
