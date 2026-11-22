"""Resume only the remaining Google-only top-60 ranking contenders.

The previous 48-shard recovery artifacts are restored as read-only inputs.
Each FSA keeps its original source queries and checkpoints. Never translate
failed, challenged, capped or ambiguous sources into zero clinical practices.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright
from research.recover_google_tiles import run_area


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fsa', required=True)
    parser.add_argument('--baseline', default='first-pass/google_all_ontario_498.csv')
    parser.add_argument('--seed-root', default='recovery-seed')
    parser.add_argument('--out', default='targeted-google')
    parser.add_argument('--seconds', type=int, default=3500)
    args = parser.parse_args()
    if args.seconds < 60 or args.seconds > 4600:
        parser.error('Time budget must be 60..4600 seconds')

    with open(args.baseline, newline='') as fh:
        audit = list(csv.DictReader(fh))
    if len(audit) != 498 or len({r['fsa'] for r in audit}) != 498:
        raise RuntimeError('Missing authoritative complete 498 FSA baseline')
    match = [r for r in audit if r['fsa'] == args.fsa]
    if len(match) != 1:
        raise RuntimeError('Unknown FSA: ' + args.fsa)
    old = match[0]
    regions = json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())['areas']
    region_match = [a for a in regions if a['fsa'] == args.fsa]
    if len(region_match) != 1:
        raise RuntimeError('Missing FSA geometry reference')
    area = region_match[0]

    root = Path(args.out) / args.fsa
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = list(Path(args.seed_root).glob('**/' + args.fsa + '.json'))
    if len(checkpoint) != 1:
        raise RuntimeError(f'Expected one historical Google FSA checkpoint for {args.fsa}; found {len(checkpoint)}')
    shutil.copy2(checkpoint[0], root / (args.fsa + '.json'))
    # Do all required tiles. Original early-dominance checks used unclassified
    # Google business titles and can wrongly dismiss clinical source gaps.
    enriched = dict(area,
                    ranking_cutoff=0.0000001,
                    population_5km_estimate=int(old['population_5km_estimate']),
                    baseline_observed_5km=int(float(old.get('google_observed_5km') or 0)))
    with sync_playwright() as pw:
        context = pw.firefox.launch_persistent_context(
            str(root / 'profile'), headless=True,
            viewport={'width': 1400, 'height': 960}, locale='en-CA')
        try:
            result = run_area(context, enriched, root, args.seconds)
        finally:
            context.close()
    print('TARGETED_GOOGLE_FSA_RESULT', json.dumps({
        'fsa': args.fsa, 'status': result['status'],
        'complete_tiles': result.get('completed_coverage_tiles'),
        'expected_tiles': result.get('total_coverage_tiles'),
        'pending_tiles': len(result.get('pending', [])),
        'capped_tiles': result.get('capped_leaf_tiles'),
        'unresolved_links': result.get('unresolved_leaf_links'),
        'raw_local_businesses': result.get('unique_observed_local_places'),
    }), flush=True)
    if result['status'] != 'verified_tile_feed':
        raise SystemExit('Google evidence remains incomplete or clinically unverified; checkpoint preserved')


if __name__ == '__main__':
    main()
