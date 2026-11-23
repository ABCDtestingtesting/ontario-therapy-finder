"""Re-score Ontario's 498 FSAs using independent Google zero-result audits.

A completed Maps feed is a bounded directory observation, never proof of the
absence of an unlisted or undiscovered therapist. Preserve source evidence,
distinguish clinical listings from ambiguous businesses, and refuse to issue
an independently certified ranking while eligible areas remain unresolved.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research.finalize_full_google_498 import clinical_title_classification

PREVIOUSLY_SCREENED={'L6Z','L7A','L6X','L6R','N1T','N3S','P5N','N4W'}
TERMS=('counselling','psychotherapy','mental health clinic')
OFFSETS=(-3.4,0.,3.4)
REQUIRED={f'independent_3term_map_grid_v1|{n}|{e}|{term}'
          for n in OFFSETS for e in OFFSETS for term in TERMS}


def csv_rows(path):
    with path.open(newline='',encoding='utf-8') as f:
        return list(csv.DictReader(f))


def export(path, rows, headers):
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore')
        w.writeheader()
        for r in rows:w.writerow(r)


def review(baseline, checkpoints, destination):
    source=csv_rows(baseline)
    if len(source)!=498 or len({r['fsa'] for r in source})!=498:
        raise RuntimeError('Expected 498 distinct census FSAs')
    zeros={r['fsa'] for r in source
           if int(r['google_therapy_locations_used_in_score'])==0
           and str(r.get('excluded_last_90_days','false')).lower()!='true'
           and str(r.get('completed_source_feed','false')).lower()=='true'}
    if len(zeros)!=53:
        raise RuntimeError('Expected exactly 53 currently verified source-zero FSAs; found '+str(len(zeros)))
    found={}
    for p in checkpoints.glob('**/[A-Z][0-9][A-Z].json'):
        if p.stem in found:raise RuntimeError('Multiple independent source checkpoints '+p.stem)
        doc=json.loads(p.read_text())
        if p.stem!=doc.get('fsa') or p.stem not in zeros:
            raise RuntimeError('Unrecognized independent FSA checkpoint '+p.stem)
        if str(doc.get('data_model_version'))!='independent_3term_map_grid_v1':
            raise RuntimeError('Independent search method changed for '+p.stem)
        observed=doc.get('observations',{})
        if not isinstance(observed,dict):raise RuntimeError('Malformed source observations '+p.stem)
        if set(observed)-REQUIRED:raise RuntimeError('Unplanned search queries for '+p.stem)
        known={}
        for key,tile in observed.items():
            if tile.get('map_area_search_verified') is not True:
                continue
            for place in tile.get('places',[]):
                key2=place.get('key')
                if not key2:raise RuntimeError('Noncanonical business ID for '+p.stem)
                known[key2]=place
        categories=Counter(clinical_title_classification(p) for p in known.values())
        fully_scoped=(set(observed)==REQUIRED and not doc.get('unverified_searches')
             and all(not tile.get('capped') and not tile.get('unresolved')
                     and tile.get('status')=='observed'
                     and tile.get('map_area_search_verified') is True
                     for tile in observed.values()))
        found[p.stem]={'doc':doc,'businesses':known,'categories':categories,
                       'fully_scoped':fully_scoped}
    reports=[]
    updated=[]
    for r in source:
        row=dict(r)
        code=row['fsa']
        pop=int(row['population_5km_estimate_2021'])
        prior_count=int(row['google_therapy_locations_used_in_score'])
        # The historical first-pass keyword result count was never item-level
        # confirmed as an actual psychotherapy or psychology practice. It
        # cannot establish a clinical competitor LOWER BOUND and must not
        # mathematically dominate a potentially stronger postal area.
        verified_recovery=int(row.get('recovery_title_confirmed_clinical_count') or 0)
        native_clinical=int(row.get('independent_google_clinical_places') or 0)
        verified_lower=max(verified_recovery,native_clinical)
        row['historical_keyword_observed_google_proxy_count']=prior_count
        row['historical_keyword_proxies_used_as_clinical_lower_bound']=False
        candidate=found.get(code)
        if code in zeros:
            row['prior_google_observed_therapy_locations']=prior_count
            row['independent_source_available']=bool(candidate)
            row['independent_source_all_27_queries_verified']=bool(candidate and candidate['fully_scoped'])
            row['independent_clinical_places']=candidate['categories']['clinical'] if candidate else 0
            row['independent_ambiguous_places']=candidate['categories']['ambiguous'] if candidate else 0
            row['independent_nonclinical_places']=candidate['categories']['nonclinical'] if candidate else 0
            row['independent_all_local_businesses']=len(candidate['businesses']) if candidate else 0
            row['independent_searches_completed']=len(candidate['doc']['observations']) if candidate else 0
            row['google_therapy_locations_used_in_score']=max(verified_lower,row['independent_clinical_places'])
            # New source evidence can overturn the previous misleading
            # complete=true. Unfinished geography or unknown clinical
            # classification must remain eligible ranking uncertainty.
            is_complete=bool(candidate and candidate['fully_scoped']
                  and candidate['categories']['ambiguous']==0)
            row['completed_source_feed']=is_complete
            row['source_evidence_status']=(
                'independent_27_google_queries_clinically_classified'
                if is_complete else 'independent_google_review_incomplete')
            reports.append({
                'fsa':code,'independent_checkpoint_available':bool(candidate),
                'all_27_queries_geographically_verified':bool(candidate and candidate['fully_scoped']),
                'verified_clinical_local_places':row['independent_clinical_places'],
                'ambiguous_local_businesses':row['independent_ambiguous_places'],
                'all_other_local_businesses':row['independent_nonclinical_places'],
                'completed_queries':row['independent_searches_completed'],
                'source_status':row['source_evidence_status']})
        else:
            row.update({
                'prior_google_observed_therapy_locations':prior_count,
                'independent_source_available':'',
                'independent_source_all_27_queries_verified':'',
                'independent_clinical_places':'',
                'independent_ambiguous_places':'',
                'independent_nonclinical_places':'',
                'independent_all_local_businesses':'',
                'independent_searches_completed':''})
            # The only locally audited clinical rows are complete Google
            # business tile sources with no unknown business specialties.
            # A numeric one-keyword Google result is a query proxy.
            exact_local=(row.get('source_evidence_status')=='local_tiled_complete'
                and str(row.get('recovery_all_local_names_clinically_classified')).lower()=='true'
                and int(row.get('recovery_pending_queries') or 0)==0
                and int(row.get('recovery_capped_base_queries') or 0)==0
                and int(row.get('recovery_unresolved_coords') or 0)==0)
            exact_native=(row.get('source_evidence_status') in (
                'native_gridded_google_complete','native_gridded_google_empty_confirmed')
                and str(row.get('independent_google_empty_log_verified')).lower()=='true')
            row['google_therapy_locations_used_in_score']=verified_lower
            row['completed_source_feed']=exact_local or exact_native
            row['source_evidence_status']=(
                'clinically_audited_local_google_tiles' if exact_local else (
                'clinically_audited_native_google_grid' if exact_native else
                'keyword_proxy_or_incomplete_clinical_evidence'))
        count=int(row['google_therapy_locations_used_in_score'])
        row['google_listings_per_10000_residents_or_lower_bound']=round(count*10000/pop,8)
        row['residents_per_google_listing_or_upper_bound']=round(pop/count,2) if count else ''
        updated.append(row)
    eligible=[r for r in updated if str(r['excluded_last_90_days']).lower()!='true'
              and r['fsa'] not in PREVIOUSLY_SCREENED]
    done=[r for r in eligible if str(r['completed_source_feed']).lower()=='true']
    order=lambda x:(float(x['google_listings_per_10000_residents_or_lower_bound']),
                    -int(x['population_5km_estimate_2021']),x['fsa'])
    done.sort(key=order)
    if len(done)<60:
        cutoff=None;unresolved=[r for r in eligible if str(r['completed_source_feed']).lower()!='true']
    else:
        cutoff=float(done[59]['google_listings_per_10000_residents_or_lower_bound'])
        unresolved=sorted((r for r in eligible
            if str(r['completed_source_feed']).lower()!='true'
            and float(r['google_listings_per_10000_residents_or_lower_bound'])<=cutoff),key=order)
    complete53=len(found)==53 and all(x['fully_scoped']
                 and x['categories']['ambiguous']==0 for x in found.values())
    certified=complete53 and cutoff is not None and len(unresolved)==0
    destination.mkdir(parents=True,exist_ok=True)
    headers=list(updated[0].keys())
    export(destination/'Ontario_Google_498_Independently_Reviewed.csv',updated,headers)
    export(destination/'Ontario_Google_53_Zero_Crosscheck.csv',reports,list(reports[0].keys()))
    export(destination/'Ontario_Google_60_New_Provisional.csv',
           [dict(rank=i,**r) for i,r in enumerate(done[:60],1)],['rank']+headers)
    export(destination/'Ontario_Google_Unresolved_Independent_Contenders.csv',
           unresolved,headers)
    if certified:
        export(destination/'Ontario_Google_Best_60_Independently_Checked.csv',
               [dict(rank=i,**r) for i,r in enumerate(done[:60],1)],['rank']+headers)
    report={
        'all_498_distinct_ontario_fsa_audited':len(updated)==498,
        'zero_fsa_rechecks_expected':53,
        'zero_fsa_rechecks_available':len(found),
        'zero_fsa_rechecks_fully_geographically_observed':sum(x['fully_scoped'] for x in found.values()),
        'zero_fsa_rechecks_clinically_classified':sum(
            x['fully_scoped'] and x['categories']['ambiguous']==0 for x in found.values()),
        'total_independently_confirmed_clinical_businesses':sum(
            x['categories']['clinical'] for x in found.values()),
        'independently_reviewed_zero_locations_claimed':False,
        'historical_keyword_proxies_accepted_as_clinical_evidence':False,
        'clinically_audited_complete_eligible_source_count':len(done),
        'fewer_than_60_clinically_audited_complete_sources':len(done)<60,
        'currently_eligible_uncertified_fsa_count':len(unresolved),
        'top_60_cutoff_observed_listings_per_10000':cutoff,
        'independent_53_zero_checks_complete':complete53,
        'google_60_independently_certified_within_observation_model':certified,
        'historical_source_certification_not_reused_as_independent_validation':True,
        'warning':'Historical first-pass Google Maps keyword counts are unclassified proxies and are excluded from confirmed therapist counts. Even 27 completed Google Maps queries do not prove an exhaustive absence of local clinicians.',
        'checked_at_utc':datetime.now(timezone.utc).isoformat(),
    }
    (destination/'Ontario_Google_Independent_Review_Report.json').write_text(json.dumps(report,indent=2))
    print('ONTARIO_INDEPENDENT_REVIEW_REPORT',json.dumps(report),flush=True)
    if not certified:
        raise RuntimeError('Independently checked 60-FSA ranking not certified; all source artifacts preserved')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--checkpoints',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    review(a.baseline,a.checkpoints,a.out)
