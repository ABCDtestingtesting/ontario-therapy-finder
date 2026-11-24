"""Ontario-wide source-completeness audit: all 521 nonzero-population Ontario 2021 FSA codes.

Earlier 498-FSA research omitted Hamilton's 22 codes. Restore them with
authoritative Statistics Canada 2021 population while explicitly marking
Google clinical office searches absent and NOT zero. The full Ontario study
must never exclude an FSA simply because it was previously researched.
"""
import argparse,csv,json,re
from pathlib import Path
from datetime import datetime,timezone
from fractions import Fraction

POP_FIELD='Population and dwelling counts (3):Population, 2021[1]'
VALID=re.compile(r'^[KLMNP][0-9][A-Z]$')

def audit(original,official,out):
    with Path(original).open(newline='',encoding='utf-8-sig') as file:
        old=list(csv.DictReader(file))
    if len(old)!=498 or len({r['fsa'] for r in old})!=498:
        raise RuntimeError('Expected exactly 498 original geographically measured Ontario FSAs')
    original_by={r['fsa']:r for r in old}
    pop={}
    with Path(official).open(newline='',encoding='utf-8-sig') as file:
        for row in csv.DictReader(file):
            code=row['GEO']
            if not VALID.fullmatch(code):continue
            if row['DGUID']!='2021A0011'+code:
                raise RuntimeError('Official 2021 FSA geography ID invalid '+code)
            count=int(row[POP_FIELD])
            if count>0:
                if code in pop:
                    raise RuntimeError('Duplicate official Ontario FSA population '+code)
                pop[code]=count
    if len(pop)!=521 or not set(original_by).issubset(pop):
        raise RuntimeError('Full provincewide 521-code FSA population source missing or mismatched')
    missing=sorted(set(pop)-set(original_by))
    if len(missing)!=23 or missing!=sorted(
        'L0R L8B L8E L8G L8H L8J L8K L8L L8M L8N L8P L8R L8S L8T L8V L8W L9A L9B L9C L9G L9H L9K M7A'.split()):
        raise RuntimeError('Missing 22 Hamilton codes plus unpolygoned M7A identity unexpected')
    rows=[]
    for code in sorted(pop):
        source=original_by.get(code)
        if source and int(source['official_2021_fsa_population'])!=pop[code]:
            raise RuntimeError('2021 FSA population mismatch '+code)
        title_count=int(source['observed_unique_title_confirmed_clinical_businesses']) if source else 0
        ambiguous_count=int(source['observed_unique_ambiguous_business_titles']) if source else 0
        nonclinical_count=int(source['observed_unique_nonclinical_businesses']) if source else 0
        coverage=float(source['share_of_official_fsa_geography_inside_original_5km_collection_discs']) if source else 0
        if not 0<=coverage<=1 or min(title_count,ambiguous_count,nonclinical_count)<0:
            raise RuntimeError('Invalid FSA Google source evidence '+code)
        rows.append({
            'fsa':code,'official_2021_population':pop[code],
            'Google_source_observed_for_FSA':bool(source),
            'observed_unique_explicitly_clinical_Google_offices_lower_bound':title_count,
            'observed_unique_ambiguous_Google_offices':ambiguous_count,
            'observed_nonclinical_Google_offices':nonclinical_count,
            'observed_clinical_offices_per_10000_residents_lower_bound':round(10000*title_count/pop[code],9),
            'all_ambiguous_businesses_assumed_clinical_upper_observed_scenario_per_10000':round(
                10000*(title_count+ambiguous_count)/pop[code],9),
            'original_Google_search_5km_circle_union_area_share':coverage,
            'FSA_geographic_search_coverage_at_least_90_percent':bool(source and coverage>=0.9),
            'definitively_all_clinical_offices_enumerated':False,
            'registered_therapist_individual_headcount_verified':False,
            'prior_research_exclusion_applied_to_2026_ranking':False,
            'count_zero_proven_by_missing_Google_source':False,
            'source_status':'original_Google_observed_incomplete' if source else 'no_Google_source_Hamilton',
        })
    ranked=sorted(rows,key=lambda r:(Fraction(r['observed_unique_explicitly_clinical_Google_offices_lower_bound'],
                                             r['official_2021_population']),-r['official_2021_population'],r['fsa']))
    screened=[r for r in ranked if r['FSA_geographic_search_coverage_at_least_90_percent']
              and r['official_2021_population']>=10000]
    if len(screened)<60:
        raise RuntimeError('Insufficient geographic source coverage to screen 60 areas')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0])
    def write(name,source,rank=False):
        with (out/name).open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,fieldnames=(['provisional_rank'] if rank else [])+fields)
            w.writeheader()
            for i,row in enumerate(source,1):
                w.writerow({'provisional_rank':i,**row} if rank else row)
    write('Ontario_ALL_521_Populated_FSA_Codes_Census_Google_Source_Audit.csv',rows)
    write('Ontario_60_Observed_Google_Lower_Bounds_NOT_CERTIFIED.csv',ranked[:60],True)
    write('Ontario_60_Geographically_Screened_Source_Leads_NOT_CERTIFIED.csv',screened[:60],True)
    report={
        'official_Ontario_nonzero_population_FSA_codes':len(pop),
        'original_clinically_screened_FSA_sources':len(original_by),
        'unsearched_Hamilton_FSA_sources':[code for code in missing if code!='M7A'],
        'unpolygoned_but_populated_special_fsa':'M7A',
        'unsearched_FSA_count':len(missing),
        '2021_geographic_boundary_polygons_available':520,
        'Ontario_2021_official_population':sum(pop.values()),
        'observed_explicit_clinical_Google_offices_lower_bound_in_scanned_areas':sum(
            r['observed_unique_explicitly_clinical_Google_offices_lower_bound'] for r in rows),
        'observed_ambiguous_Google_offices_in_scanned_areas':sum(
            r['observed_unique_ambiguous_Google_offices'] for r in rows),
        'FSA_sources_with_90percent_geographic_disc_coverage':sum(
            r['FSA_geographic_search_coverage_at_least_90_percent'] for r in rows),
        'low_competition_sources_geographically_screened_with_10k_residents':len(screened),
        'previously_excluded_FSA_sources_restored_to_ranking':8,
        'proves_all_registered_therapists_counted':False,
        'certified_lowest_60_per_capita_therapist_FSAs':False,
        'sampling_limitation':'Google offices, not individual therapist headcounts. No exhaustive source. 22 Hamilton FSA source searches absent, plus M7A (5 residents; no FSA boundary polygon); previous geographic collection covered just the original 5-km disc unions.',
        'verified_at_utc':datetime.now(timezone.utc).isoformat(),
    }
    (out/'Ontario_521_Provincial_Research_Completeness.json').write_text(json.dumps(report,indent=2))
    print('OFFICIAL_ALL_521_ONTARIO_FSA_CODES_RECONCILIATION',json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for a in ('original','official','out'):p.add_argument('--'+a,required=True,type=Path)
    a=p.parse_args()
    audit(a.original,a.official,a.out)
