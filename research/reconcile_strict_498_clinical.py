"""Merge Google clinical audits without switching from the agreed 5-km catchment.
Business searches and directory results are observed lower bounds, not a census.
Source complete means verified within that Google observation model alone.
"""
import argparse,csv,json
from datetime import datetime,timezone
from pathlib import Path
from fractions import Fraction

EXCLUDE={'L6Z','L7A','L6X','L6R','N1T','N3S','P5N','N4W'}

def read(path):
    with Path(path).open(newline='',encoding='utf8') as f: records=list(csv.DictReader(f))
    if len(records)!=498 or len({r['fsa'] for r in records})!=498:
        raise RuntimeError('Expected 498 distinct Ontario FSAs')
    return {r['fsa']:r for r in records}

def truth(s):
    if str(s).lower() not in ('true','false'):
        raise RuntimeError('Malformed boolean in source: '+str(s))
    return str(s).lower()=='true'

def natural(s,code):
    try: result=int(s)
    except (ValueError,TypeError) as exc: raise RuntimeError('Invalid source count '+code) from exc
    if result<0: raise RuntimeError('Negative source count '+code)
    return result

def reconcile(strict,category,out):
    left,right=read(strict),read(category)
    if set(left)!=set(right): raise RuntimeError('Mismatched Ontario FSA cohorts')
    rows=[]
    for code in sorted(left):
        a,b=left[code],right[code]
        pop=natural(a['population_5km_estimate_2021'],code)
        if not pop or pop!=natural(b['population_5km_estimate_2021'],code):
            raise RuntimeError('2021 five-km catchment population mismatch '+code)
        if max(abs(float(a[k])-float(b[k])) for k in ('latitude','longitude'))>0.000001:
            raise RuntimeError('FSA centroid mismatch '+code)
        if truth(a['excluded_last_90_days'])!=truth(b['excluded_last_90_days']):
            raise RuntimeError('Recent research exclusion mismatch '+code)
        if (not a['original_google_place_source_sha256']
            or a['original_google_place_source_sha256']!=b['firstpass_google_source_sha256']):
            raise RuntimeError('Original Google source provenance mismatch '+code)
        clinic_a=natural(a['google_observed_therapy_locations_lower_bound'],code)
        clinic_b=natural(b['confirmed_clinical_business_lower_bound'],code)
        original=natural(b['firstpass_title_confirmed_clinical_places'],code)
        if clinic_b<original: raise RuntimeError('Category audit discarded confirmed clinic '+code)
        clinic=max(clinic_a,clinic_b)
        source_complete=truth(a['completed_source_feed'])
        independent_conflict=clinic_b>clinic_a
        # Older Google source completion did not establish that the list
        # matched the tile's requested geography. The observed clinic
        # count is retained, but the source cannot be called complete.
        merged_complete=False
        rows.append({
          'fsa':code,
          'population_within_5km_2021_estimate':pop,
          'source_a_clinical_office_lower_bound':clinic_a,
          'source_b_clinical_office_lower_bound':clinic_b,
          'cross_source_clinical_office_lower_bound':clinic,
          'observed_clinical_offices_per_10000_lower_bound':round(10000*clinic/pop,9),
          'residents_per_observed_clinical_office_upper_bound':round(pop/clinic,2) if clinic else '',
          'source_a_grid_clinically_complete':False,
          'source_a_legacy_completion_flag_before_geo_revalidation':source_complete,
          'source_b_detected_additional_clinical_offices':independent_conflict,
          'merged_google_observation_source_complete':merged_complete,
          'previously_screened_excluded':code in EXCLUDE or truth(a['excluded_last_90_days']),
          'Google_proves_no_unlisted_clinicians':False,
          'Google_listing_is_individual_therapist':False,
          '2021_fsa_centroid_latitude':a['latitude'],
          '2021_fsa_centroid_longitude':a['longitude'],
          'original_source_sha256':a['original_google_place_source_sha256'],
        })
    eligible=[r for r in rows if not r['previously_screened_excluded']]
    key=lambda r:(Fraction(r['cross_source_clinical_office_lower_bound'],
                            r['population_within_5km_2021_estimate']),
                  -r['population_within_5km_2021_estimate'],r['fsa'])
    ranked=sorted(eligible,key=key)
    verified=[r for r in ranked if r['merged_google_observation_source_complete']]
    cutoff_key=key(verified[59]) if len(verified)>=60 else None
    cutoff=float(cutoff_key[0])*10000 if cutoff_key is not None else None
    unresolved=[r for r in ranked if not r['merged_google_observation_source_complete']
      and (cutoff_key is None or key(r)<=cutoff_key)]
    certified=cutoff_key is not None and not unresolved
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    columns=list(rows[0])
    def save(name,items,rank=False):
        with (out/name).open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,fieldnames=(['provisional_rank'] if rank else [])+columns)
            w.writeheader()
            for i,r in enumerate(items,1):
                w.writerow({'provisional_rank':i,**r} if rank else r)
    save('Ontario_498_Strict_5km_Google_Clinical_Crossaudit.csv',rows)
    save('Ontario_498_Unresolved_Potential_Rank_Contenders.csv',unresolved)
    save('Ontario_60_5km_Observed_Google_Competition_NOT_CERTIFIED.csv',ranked[:60],True)
    if certified:
        save('Ontario_60_Certified_Within_Google_Source_Observation_Model.csv',verified[:60],True)
    report={
        'crosschecked_2021_5km_fsa_sources':498,
        'eligible_areas_after_eight_and_recent_exclusions':len(eligible),
        'fully_clinically_audited_eligible_sources':len(verified),
        'legacy_google_completed_sources_revoked_pending_geographic_validation':
            sum(r['source_a_legacy_completion_flag_before_geo_revalidation'] for r in rows),
        'areas_where_additional_google_clinics_found':sum(r['source_b_clinical_office_lower_bound']>r['source_a_clinical_office_lower_bound'] for r in rows),
        'previously_complete_sources_with_new_unaccounted_clinics':sum(r['source_a_grid_clinically_complete'] and r['source_b_detected_additional_clinical_offices'] for r in rows),
        'unresolved_potential_top60_contenders':len(unresolved),
        'certification_cutoff_per_10000':cutoff,
        'certified_top60_within_google_source_model':certified,
        'proves_no_unlisted_therapists':False,
        'denominator':'Statistics Canada 2021 DA-based population estimate within 5 km of each FSA center',
        'numerator':'max of two item-level geolocated clinical Google office observation counts; duplicate-prone sources never summed',
        'source_limitations':'Business locations, not therapist headcounts; Google may omit businesses; complete search is only observed Google source completeness',
        'updated_at_utc':datetime.now(timezone.utc).isoformat()
    }
    (out/'Ontario_498_Strict_5km_Crossaudit_Report.json').write_text(json.dumps(report,indent=2))
    print('STRICT_ONTARIO_498_FSA_CLINICAL_CROSSAUDIT',json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--strict',type=Path,required=True)
    p.add_argument('--categories',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    reconcile(a.strict,a.categories,a.out)
