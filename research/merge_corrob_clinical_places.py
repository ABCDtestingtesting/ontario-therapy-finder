"""Restore independently corroborated clinics from original geolocated Google
place evidence into each five-kilometre FSA observed LOWER bound.
Duplicates across search queries never sum; existing stronger counts survive.
"""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from fractions import Fraction
from datetime import datetime,timezone
from research.external_google_clinical_adjudications import (
    independent_clinical_service_evidence, independent_nonclinical_service_evidence)

def run(prior:Path,raw:Path,out:Path):
    with prior.open(newline='',encoding='utf8') as fh:
        data=list(csv.DictReader(fh))
    if len(data)!=498 or len({x['fsa'] for x in data})!=498:
        raise RuntimeError('Exactly 498 unique Ontario source rows required')
    src=json.loads(raw.read_text())
    if src.get('source_type')!='geographically verified Google Maps place listings':
        raise RuntimeError('Original Google place provenance absent')
    by_fsa=src['all_places_by_fsa']
    if set(by_fsa)!={x['fsa'] for x in data}:
        raise RuntimeError('Google original places missing FSA sources')
    report=[]
    for row in data:
        code=row['fsa']
        places=by_fsa[code]
        proof={p['key']:p for p in places if independent_clinical_service_evidence(p)}
        nonclinical={p['key']:p for p in places if independent_nonclinical_service_evidence(p)}
        if len(proof)>len(places):
            raise RuntimeError('Evidence deduplication failed '+code)
        original_count=int(row['cross_source_clinical_office_lower_bound'])
        observed=max(original_count,len(proof))
        if original_count<0:raise RuntimeError('Negative clinic lower bound')
        changed=observed>original_count
        previous_complete=row['merged_google_observation_source_complete']=='True'
        row['cross_source_clinical_office_lower_bound']=str(observed)
        row['merged_google_observation_source_complete']=str(previous_complete and not changed)
        pop=int(row['population_within_5km_2021_estimate'])
        if pop<=0:raise RuntimeError('Missing census catchment '+code)
        row['observed_clinical_offices_per_10000_lower_bound']=str(round(10000*observed/pop,9))
        row['residents_per_observed_clinical_office_upper_bound']=str(round(pop/observed,2)) if observed else ''
        row['new_externally_corrob_clinics']=str(len(proof))
        row['new_externally_corrob_nonclinical_titles']=str(len(nonclinical))
        if proof or nonclinical:
            report.append({'fsa':code,'prior_clinics':original_count,'new_lower_bound':observed,
                'increase':observed-original_count,
                'clinical_google_places':{key:independent_clinical_service_evidence(p) for key,p in proof.items()},
                'nonclinical_google_places':{key:independent_nonclinical_service_evidence(p) for key,p in nonclinical.items()}})
    rank=lambda x:(Fraction(int(x['cross_source_clinical_office_lower_bound']),
                            int(x['population_within_5km_2021_estimate'])),
                    -int(x['population_within_5km_2021_estimate']),x['fsa'])
    eligible=sorted([row for row in data if row['previously_screened_excluded']=='False'],key=rank)
    completed=sorted([row for row in eligible if row['merged_google_observation_source_complete']=='True'],key=rank)
    cutoff=rank(completed[59]) if len(completed)>=60 else None
    unresolved=[row for row in eligible if row['merged_google_observation_source_complete']!='True'
                and (cutoff is None or rank(row)<=cutoff)]
    ready=cutoff is not None and not unresolved
    out.mkdir(parents=True,exist_ok=True)
    fields=list(data[0])
    def save(name,items,numbered=False):
        with (out/name).open('w',newline='',encoding='utf8') as fh:
            columns=(['rank'] if numbered else [])+fields
            writer=csv.DictWriter(fh,fieldnames=columns)
            writer.writeheader()
            for i,row in enumerate(items,1):writer.writerow({'rank':i,**row} if numbered else row)
    save('Ontario_498_With_Independently_Corroborated_Clinic_Evidence.csv',sorted(data,key=lambda x:x['fsa']))
    save('Ontario_Unresolved_Clinical_Competition_Contenders.csv',unresolved)
    save('Ontario_Observed_60_Clinical_Lower_Bounds_NOT_CERTIFIED.csv',eligible[:60],True)
    if ready:save('Ontario_60_Certified_Within_Observed_Google_Model.csv',completed[:60],True)
    summary={'observed_original_fsa_cohort':498,
      'external_clinical_google_businesses_with_matching_source_in_fsas':sum(len(x['clinical_google_places']) for x in report),
      'source_title_nonclinical_corrections':sum(len(x['nonclinical_google_places']) for x in report),
      'areas_with_new_positive_clinic_lower_bounds':sum(x['increase']>0 for x in report),
      'clinic_lower_bound_increase':sum(x['increase'] for x in report),
      'remaining_rank_contenders':len(unresolved),
      'clinically_complete_eligible_sources':len(completed),
      'final60_source_model_certified':ready,
      'source_clinic_adjudications':report,
      'individual_clinician_headcounts_proven':False,
      'time_utc':datetime.now(timezone.utc).isoformat()}
    (out/'Ontario_Clinic_External_Corroboration_Report.json').write_text(json.dumps(summary,indent=2))
    print('CLINICAL_PROOF_498_AUDIT',json.dumps({k:v for k,v in summary.items() if k!='source_clinic_adjudications'}),flush=True)
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('prior','raw','out'):
        parser.add_argument('--'+name,required=True,type=Path)
    a=parser.parse_args()
    run(a.prior,a.raw,a.out)
