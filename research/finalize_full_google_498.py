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
import math
import re
from research.external_google_clinical_adjudications import independent_clinical_service_evidence, independent_nonclinical_service_evidence
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED = {'L6Z', 'L7A', 'L6X', 'L6R', 'N1T', 'N3S', 'P5N', 'N4W'}
SOURCE_STATUS = 'confirmed_observed_feed'
# A Google search can return physiotherapy, animal services and other businesses
# even for a psychotherapist query. Names without an explicit mental-health
# designation must not count towards a PROVEN clinical-location lower bound.
CLINICAL_TITLE_TERMS = (
    # Generic 'counselling' can describe credit, career, debt or legal
    # advice. Require an explicit mental-health qualification or a verified
    # Google Maps clinical business category instead.
    'psychotherap', 'psycholog', 'family therap', 'marriage therap',
    'mental health counsel', 'mental health counsell',
    'counselling and mental health centre',
    'mental health therap', 'clinical social work',
    'registered psychotherapist',
)
NONCLINICAL_TITLE_TERMS = (
    'physiotherap', 'physical therap', 'physio', 'chiropract', 'massage',
    'naturopath', 'pharmacy', 'veterinar', 'animal shelter',
    'conservation area', 'dog ', 'pet ', 'fitness', 'acupuncture',
    'dental', 'dentist', 'sport injury', 'sports injury',
    'speech therapy', 'real estate',
    'career counsel', 'career counsell', 'career guidance',
    'credit counsel', 'credit counsell', 'debt counsel', 'debt counsell',
    'financial counsel', 'financial counsell', 'financial planning',
    'employment counsel', 'employment counsell', 'vocational counsel',
    'academic counsel', 'academic counsell', 'career development',
)


def clinical_title_classification(place):
    """Classify by explicit title evidence; unrecognized titles remain unknown."""
    name = str(place.get('name') or '').casefold().strip()
    if not name:
        return 'ambiguous'
    # Google Maps sometimes returns a named settlement as a business.
    # These exact positions are corroborated by official Canadian place
    # records (Lisle, Ontario and Craighurst, Ontario). Match the settlement
    # itself at its known coordinates, never a clinic named after the town.
    geographic_places = {
        'lisle': (44.268, -79.977),
        'craighurst': (44.52914, -79.72567),
    }
    if name in geographic_places:
        place_lat, place_lon = geographic_places[name]
        try:
            if (abs(float(place.get('lat')) - place_lat) < .002 and
                    abs(float(place.get('lon')) - place_lon) < .002 and
                    '/maps/place/' in str(place.get('source_url') or '')):
                return 'nonclinical'
        except (TypeError, ValueError):
            pass
    if any(term in name for term in NONCLINICAL_TITLE_TERMS):
        return 'nonclinical'
    if independent_nonclinical_service_evidence(place):
        return 'nonclinical'
    if independent_clinical_service_evidence(place):
        return 'clinical'
    if any(term in name for term in CLINICAL_TITLE_TERMS):
        return 'clinical'
    # Exact Google Maps business-detail categories are stronger evidence than
    # a vague business title. Unknown categories remain ambiguous; a scraped
    # search term or a guessed business specialty never counts as evidence.
    category = str(place.get('google_business_category') or '').casefold().strip()
    if category:
        # 'Mental health service' includes peer support and advocacy groups.
        # A generic social-work registration or NGO name does not prove the
        # organization offers psychotherapy or psychological treatment.
        clinical_categories = ('psychotherap', 'psycholog',
            'mental health counsel', 'mental health counsell',
            'mental health clinic', 'family therap',
            'marriage or relationship counsel')
        nonclinical_categories = ('physiotherap', 'chiropract', 'physical therap',
            'occupational therap', 'massage therap', 'acupunctur', 'life coach',
            'veterinar', 'church', 'wellness center', 'wellness centre',
            'health food store', 'kennel', 'osteopath', 'industrial consultant',
            'horse riding school', 'research institute', 'skin care clinic',
            'dentist', 'pharmacy', 'speech patholog',
            'speech therap', 'naturopath', 'yoga studio',
            'career guidance', 'career counselor', 'career counsellor',
            'employment center', 'employment centre',
            'credit counseling', 'credit counselling',
            'debt counseling', 'debt counselling',
            'financial advisor', 'financial consultant',
            'education consultant')
        # Google can categorize credit/debt/career advice as counselling.
        # Reject an explicitly nonclinical category before matching any
        # overlapping mental-health wording. "Counselor" alone is ambiguous.
        if any(term in category for term in nonclinical_categories):
            return 'nonclinical'
        if any(term in category for term in clinical_categories):
            return 'clinical'
    return 'ambiguous'


def confirmed_clinical_title(place):
    return clinical_title_classification(place) == 'clinical'


def clinical_recovery_lower_bound(source):
    """Only title-confirmed counselling/psychotherapy listings count as proven.

    Ambiguous businesses remain in the original evidence for manual review.
    Omitting one from this bound is conservative: it may increase the number of
    unresolved ranking contenders, but cannot falsely rule an area out.
    """
    if not source:
        return 0
    places = source.get('local_places') or []
    if not isinstance(places, list):
        raise RuntimeError('Malformed recovered Google location list')
    return sum(confirmed_clinical_title(p) for p in places)


def recovery_geographically_verified(source):
    """Reject remotely scoped Google results even if the viewport was centred."""
    if not source:
        return False
    tiles=source.get('complete_tiles') or {}
    offsets=(-3.4,0.0,3.4)
    terms=('psychotherapist','psychologist')
    required={'map_movement_v7_checkbox_on|'+'|'.join(map(str,(n,e,0,t)))
              for n in offsets for e in offsets for t in terms}
    if not required.issubset(tiles):
        return False
    for key in required:
        item=tiles[key]
        if (item.get('status')!='observed'
            or item.get('map_area_search_verified') is not True
            or item.get('capped')
            or item.get('unresolved')
            or item.get('geographic_result_scope_verified') is False):
            return False
        if not item.get('places'):
            if item.get('visible_links') is None:
                return False
            if int(item['visible_links'])>0 or item.get('reason')!='explicit_no_results':
                return False
    return True


def recovery_clinically_classified(source):
    if not source:
        return False
    places = source.get('local_places') or []
    return (isinstance(places, list)
            and len(places) == int(source.get('unique_observed_local_places') or 0)
            and all(clinical_title_classification(place) != 'ambiguous'
                    for place in places))


def as_bool(value):
    return str(value).lower() == 'true'


def source_complete(original):
    return original['status'] == SOURCE_STATUS and not as_bool(original['feed_capped']) and int(original['unlocated_links']) == 0


def independent_grid_searches_complete(meta, path):
    """Require every expected Google Maps grid search to finish successfully."""
    if meta.get('process_returncode') != 0:
        return False
    p = Path(path)
    plan, log = p.parent / 'run_plan.json', p.parent / 'collector.log'
    if not plan.is_file() or not log.is_file():
        return False
    try:
        conf = json.loads(plan.read_text())
        south, west, north, east = map(float, conf['bbox'].split(','))
        cell = float(conf['grid_cell_km'])
        nterms = len(conf['terms'])
        if not (0 < cell <= 5 and south < north and west < east and nterms == 4):
            return False
        mid = (south+north)/2
        rows = math.ceil((north-south) / (cell/111.32))
        cols = math.ceil((east-west) / (cell/(111.32*math.cos(math.radians(mid)))))
        expected = rows*cols*nterms
        if expected < 4 or expected > 500:
            return False
        completed = set()
        exited = False
        observed_search_responses = 0
        max_reported_places = 0
        with log.open(encoding='utf8',errors='replace') as logfile:
            for line in logfile:
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if event.get('message') == 'scrapemate exited':
                    exited = True
                message = str(event.get('message') or '')
                if message.endswith(' places found'):
                    try:
                        reported = int(message.split(' ',1)[0])
                        if reported > 0:
                            observed_search_responses += 1
                            max_reported_places = max(max_reported_places, reported)
                    except ValueError:
                        pass
                if (event.get('message') != 'job finished'
                    or event.get('status') != 'success'
                    or '/maps/search/' not in event.get('job','')):
                    continue
                match = re.search(r'URL: (https://www.google.com/maps/search/\S+?)(?:, UrlParams:|})', event['job'])
                if not match:
                    continue
                url = match.group(1)
                point = re.search(r'/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),',url)
                if point:
                    lat,lon=map(float,point.groups())
                    if south <= lat <= north and west <= lon <= east:
                        completed.add(url)
        # Google grid search results must actually have been written to disk.
        # The collector sometimes logs 70 places returned for an individual
        # search but emits a CSV with only 2-4 detail rows (or no file).
        # Such truncated detail output is never a completed provider census.
        csv_file = p.parent / 'native_google_raw.csv'
        if not csv_file.is_file():
            return False
        with csv_file.open(newline='', encoding='utf-8-sig') as fh:
            reader = csv.DictReader(fh)
            if not {'title', 'latitude', 'longitude', 'link'} <= set(reader.fieldnames or []):
                return False
            actual_rows = sum(1 for _ in reader)
        return (exited and len(completed) == expected
                and observed_search_responses > 0
                and actual_rows == int(meta.get('raw_rows') or 0)
                and actual_rows >= max_reported_places)
    except (OSError,KeyError,TypeError,ValueError,ZeroDivisionError):
        return False


def independent_grid_empty_evidenced(meta, path):
    """Prove empty Google source output only after all grid queries succeeded."""
    # Some collectors exited zero with an EMPTY 0-byte CSV while their logs
    # reported successful Google search jobs. A missing output cannot prove
    # zero local therapists. Only an explicitly verified, parseable empty
    # source may qualify; older source_failed/grid_empty_unconfirmed records
    # must remain censored.
    p = Path(path)
    csv_file = p.parent / 'native_google_raw.csv'
    if (meta.get('status') != 'grid_empty_verified'
        or meta.get('process_returncode') != 0
        or meta.get('raw_rows') != 0
        or meta.get('source_empty_or_missing')
        or not csv_file.is_file()):
        return False
    try:
        with csv_file.open(newline='', encoding='utf-8-sig') as fh:
            reader = csv.DictReader(fh)
            if not {'title', 'latitude', 'longitude', 'link'} <= set(reader.fieldnames or []):
                return False
            if next(reader, None) is not None:
                return False
    except (OSError, UnicodeError, csv.Error):
        return False
    return independent_grid_searches_complete(meta, path)


def combine(first_pass, recovery_root, output, native_root=None, original_clinical_audit=None, allow_uncertified_audit=False):
    with open(first_pass, newline='') as fh:
        originals = list(csv.DictReader(fh))
    if len(originals) != 498 or len({r['fsa'] for r in originals}) != 498:
        raise RuntimeError('Expected 498 distinct populated Ontario postal code areas')
    original_place_evidence = {}
    if original_clinical_audit is not None:
        with open(original_clinical_audit, newline='', encoding='utf8') as clinical_file:
            preserved = list(csv.DictReader(clinical_file))
        if len(preserved) != 498 or {x['fsa'] for x in preserved} != {x['fsa'] for x in originals}:
            raise RuntimeError('Original item-level Google clinical source must cover 498 distinct Ontario FSAs')
        for row in preserved:
            code = row['fsa']
            if code in original_place_evidence:
                raise RuntimeError('Duplicate item-level clinical evidence for '+code)
            clinical = int(row['firstpass_clinical_title_lower_bound'])
            ambiguous = int(row['firstpass_ambiguous_titles'])
            nonclinical = int(row['firstpass_nonclinical_titles'])
            total = int(row['original_google_located_businesses'])
            digest = row['firstpass_source_shard_sha256']
            if (min(clinical, ambiguous, nonclinical) < 0
                    or clinical+ambiguous+nonclinical != total):
                raise RuntimeError('Invalid Google business clinical source partition '+code)
            if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                raise RuntimeError('Missing original Google place source SHA256 '+code)
            original_place_evidence[code] = row

    recovery = {}
    for path in Path(recovery_root).glob('**/[A-Z][0-9][A-Z].json'):
        item = json.loads(path.read_text())
        code = item['fsa']
        if code in recovery:
            raise RuntimeError('Duplicate Google tile recovery FSA: ' + code)
        recovery[code] = item

    native = {}
    native_paths = {}
    if native_root:
        for path in Path(native_root).glob('**/native_evidence.json'):
            item = json.loads(path.read_text())
            code = item.get('fsa')
            if not code or code in native:
                raise RuntimeError('Duplicate or malformed independent native Google evidence')
            native[code] = item
            native_paths[code] = path

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
        raw_recovered = int(source.get('unique_observed_local_places') or 0) if source else 0
        observed_recovered = clinical_recovery_lower_bound(source)
        independent = native.get(code)
        independent_observed = int(independent.get('unique_clinical_local_places') or 0) if independent else 0
        # Never add counts from distinct searches: overlaps cannot be assumed
        # disjoint without canonical Google place IDs. Max is a valid bound.
        # Keyword-only Google counts are not clinically verified and cannot
        # be used as a lower bound on psychotherapists or psychologists.
        # The original first-pass source includes individual geolocated Google
        # business evidence. Only unambiguous clinical titles contribute.
        original_clinical = (int(original_place_evidence[code]['firstpass_clinical_title_lower_bound'])
                             if code in original_place_evidence else 0)
        lower = max(original_clinical, observed_recovered, independent_observed)
        # Distinct Google searches cannot be summed without place-level
        # deduplication. The maximum of two observed counts is a safe minimum.
        base_ok = source_complete(old)
        # Some Google links omit their coordinates. A uniquely identified
        # business may be excluded from the study radius when its independent
        # PRIMARY office location is verifiably in a distant town. The
        # original Google URL and uncertainty remain in the audit record.
        exterior_verified = bool(
            source and code == 'N0L'
            and source.get('status') == 'verified_local_tiles_with_exterior_exception'
            and len(source.get('externally_verified_exterior_links', [])) == 1
            and source['externally_verified_exterior_links'][0].get(
                'outside_region_from_primary_office_evidence') is True
            and source['externally_verified_exterior_links'][0].get(
                'google_place_key') == '0x131ec0f0e46a697:0x99076c9617b15499'
            and int(source.get('unresolved_leaf_links') or 0) == 1)
        recovered_ok = bool(source and source.get('status') in (
                                'verified_tile_feed',
                                'verified_local_tiles_with_exterior_exception')
                            and not source.get('pending')
                            and not source.get('capped_leaf_tiles')
                            and (not source.get('unresolved_leaf_links')
                                 or exterior_verified)
                            and recovery_clinically_classified(source)
                            and recovery_geographically_verified(source)
                            and observed_recovered >= original_clinical)
        native_ok = bool(independent
                         and independent.get('status') == 'grid_observed_complete'
                         and independent.get('process_returncode') == 0
                         and independent.get('raw_rows', 0) > 0
                         and not independent.get('bad_coordinates')
                         and independent_observed >= original_clinical
                         and independent_grid_searches_complete(independent,native_paths[code]))
        native_empty_ok = bool(independent
                               and original_clinical == 0
                               and independent_grid_empty_evidenced(independent, native_paths[code]))
        if native_ok or native_empty_ok:
            # Complete the bounded Google source observation, including proven
            # empty output. This never claims all therapists were enumerated.
            # Different source searches may omit otherwise visible local
            # businesses. Keep the maximum observed local count as a
            # conservative bound instead of replacing larger source evidence.
            count = lower
            exact = True
            status = 'native_gridded_google_complete' if native_ok else 'native_gridded_google_empty_confirmed'
        elif recovered_ok:
            count = lower
            exact = True
            status = 'local_tiled_complete'
        else:
            count = lower
            exact = False
            status = 'censored_or_incomplete'
        if count < 0:
            raise RuntimeError('Negative Google observed places for ' + code)
        # Zero observed Google businesses is a legitimate observed density of 0.
        # A missing/incomplete zero must NEVER be excluded by replacing 0
        # with an imaginary one-business denominator.
        observed_density = count * 10000.0 / pop
        residents_per_listing = round(pop / count, 2) if count else None
        quality[status] += 1
        rows.append({
            'fsa': code,
            'population_5km_estimate_2021': pop,
            'google_observed_therapy_locations_lower_bound': lower,
            'historical_keyword_observed_google_proxy_count': baseline,
            'historical_keyword_proxies_used_as_clinical_lower_bound': False,
            'historical_keyword_feed_complete': base_ok,
            'original_google_clinical_title_lower_bound': original_clinical,
            'original_google_place_source_sha256': original_place_evidence[code]['firstpass_source_shard_sha256'] if code in original_place_evidence else '',
            'google_therapy_locations_used_in_score': count,
            'google_listings_per_10000_residents_or_lower_bound': round(observed_density, 8),
            'residents_per_google_listing_or_upper_bound': residents_per_listing,
            'completed_source_feed': exact,
            'source_evidence_status': status,
            'excluded_last_90_days': previous,
            'latitude': old['latitude'],
            'longitude': old['longitude'],
            'google_first_pass_search_url': old['source_url'],
            'recovery_complete_tiles': len(source.get('complete_tiles', {})) if source else 0,
            'recovery_raw_google_place_count': raw_recovered,
            'recovery_title_confirmed_clinical_count': observed_recovered,
            'recovery_explicitly_nonclinical_count': sum(
                clinical_title_classification(place) == 'nonclinical'
                for place in (source.get('local_places') or [])) if source else 0,
            'recovery_ambiguous_business_titles_count': sum(
                clinical_title_classification(place) == 'ambiguous'
                for place in (source.get('local_places') or [])) if source else 0,
            'recovery_all_local_names_clinically_classified': recovery_clinically_classified(source),
            'recovery_status': source.get('status') if source else '',
            'recovery_pending_queries': len(source.get('pending', [])) if source else None,
            'recovery_capped_base_queries': source.get('capped_leaf_tiles') if source else None,
            'recovery_unresolved_coords': source.get('unresolved_leaf_links') if source else None,
            'recovery_exterior_place_manual_reviews': len(source.get('externally_verified_exterior_links', [])) if source else 0,
            'independent_google_grid_status': independent.get('status') if independent else '',
            'independent_google_raw_rows': independent.get('raw_rows') if independent else None,
            'independent_google_clinical_places': independent_observed,
            'independent_google_source_sha256': independent.get('raw_csv_sha256') if independent else None,
            'independent_google_empty_log_verified': native_empty_ok,
        })

    verified = sorted((r for r in rows if r['completed_source_feed']
                       and not r['excluded_last_90_days']),
                      key=lambda r: (r['google_listings_per_10000_residents_or_lower_bound'],
                                     -r['population_5km_estimate_2021'], r['fsa']))
    cutoff = (verified[59]['google_listings_per_10000_residents_or_lower_bound']
              if len(verified) >= 60 else None)
    contenders = sorted((r for r in rows if not r['completed_source_feed']
                         and not r['excluded_last_90_days']
                         and (cutoff is None or r['google_listings_per_10000_residents_or_lower_bound'] <= cutoff)),
                        key=lambda r: (r['google_listings_per_10000_residents_or_lower_bound'],
                                       -r['population_5km_estimate_2021'], r['fsa']))
    safe_to_exclude = [r for r in rows if not r['completed_source_feed']
                       and not r['excluded_last_90_days']
                       and cutoff is not None
                       and r['google_listings_per_10000_residents_or_lower_bound'] > cutoff]
    certified = cutoff is not None and not contenders
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
    write_csv('Ontario_Google_Clinically_Completed_Source_Subset.csv', verified, rank=True)
    if len(verified) >= 60:
        write_csv('Ontario_Google_Top60_Completed_Feeds_Provisional.csv', verified[:60], rank=True)
    write_csv('Ontario_Google_Unresolved_Ranking_Contenders.csv', contenders)
    if certified:
        write_csv('Ontario_Google_Best_60_Across_498.csv', verified[:60], rank=True)

    report = {
        'total_ontario_fsa': len(rows),
        'first_pass_complete': 0,
        'historical_complete_keyword_only_business_feeds': sum(source_complete(old) for old in originals),
        'clinically_completed_eligible_fsa': len(verified),
        'original_item_level_clinical_source_fsa_count': len(original_place_evidence),
        'original_item_level_clinical_lower_bound_total': sum(int(r['firstpass_clinical_title_lower_bound']) for r in original_place_evidence.values()),
        'recovery_source_complete': quality['local_tiled_complete'],
        'independent_google_grid_source_complete': quality['native_gridded_google_complete'],
        'independent_google_grid_empty_confirmed': quality['native_gridded_google_empty_confirmed'],
        'other_incomplete_google_sources': quality['censored_or_incomplete'],
        'dominated_incomplete_sources': len(safe_to_exclude),
        'potential_top_60_contenders_unresolved': len(contenders),
        'top_60_cutoff_observed_google_listings_per_10000_residents': cutoff,
        'google_60_certified_within_source_observation_model': certified,
        'certification_rule': 'All incomplete source LOWER BOUNDS on Google listings per 10,000 must exceed the 60th completed-source observed density; zero lower bound is always a contender at a positive cutoff',
        'note': 'Google keyword business counts are excluded from clinical lower bounds and completion. Completed Google search feed means the configured search finished, not exhaustive clinician coverage. Native source_failed zero-byte CSVs cannot prove zero; recovery names not clearly counselling or psychology are excluded from confirmed clinical counts. First-pass numeric Google keyword results have no item-level clinical audit and remain directory-search proxies; a final ranking must not be mistaken for proven therapist counts.',
        'psychology_today_used': False,
        '2021_population_source': 'Statistics Canada',
        'checked_at_utc': datetime.now(timezone.utc).isoformat()
    }
    (out / 'google_498_recovery_report.json').write_text(json.dumps(report, indent=2))
    print('ONTARIO_GOOGLE_498_COVERAGE', json.dumps(report), flush=True)
    if not certified and not allow_uncertified_audit:
        raise RuntimeError(f'{len(contenders)} incompletely observed areas could still enter the top 60; provisional ranked list and complete audit preserved')
    if not certified:
        print('SOURCE_AUDIT_SUCCESS_CERTIFICATION_BLOCKED',
              json.dumps({'unresolved_eligible_sources':len(contenders),
                          'clinically_complete_eligible_sources':len(verified),
                          'top_60_ready':False}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('first_pass')
    parser.add_argument('recovery_root')
    parser.add_argument('output')
    parser.add_argument('--native-root', default=None)
    parser.add_argument('--original-clinical-audit', default=None)
    parser.add_argument('--allow-uncertified-audit', action='store_true')
    args = parser.parse_args()
    combine(args.first_pass, args.recovery_root, args.output, args.native_root, args.original_clinical_audit, args.allow_uncertified_audit)
