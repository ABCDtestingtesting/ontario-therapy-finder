"""Integrate actual geolocated Google business evidence into Ontario's 498-FSA
competition study. The first-pass title-confirmed counts are LOWER BOUNDS,
not therapist census totals; no unknowns or query proxies become verified.
Never certify the final 60 while ranking contenders remain unresolved.
"""
from __future__ import annotations
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_RECENT={'L6Z','L7A','L6X','L6R','N1T','N3S','P5N','N4W'}


def load_csv(path):
    with path.open(newline='',encoding='utf8') as file:
        return list(csv.DictReader(file))


def write_csv(path,records,fields):
    with path.open('w',newline='',encoding='utf8') as out:
        writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def analyze(independent_path,original_path,dest):
    audited=load_csv(independent_path)
    originals=load_csv(original_path)
    if len(audited)!=498 or len(originals)!=498:
        raise RuntimeError('Both complete 498-FSA source audits are required')
    orig={r['fsa']:r for r in originals}
    if len(orig)!=498 or len({r['fsa'] for r in audited})!=498:
        raise RuntimeError('Missing or duplicated Ontario FSAs')
    updated=[]
    for row in audited:
        code=row['fsa']
        if code not in orig:
            raise RuntimeError('FSA absent from original Google place evidence: '+code)
        source=orig[code]
        if source['firstpass_source_shard_sha256']=='':
            raise RuntimeError('Missing Google source provenance for '+code)
        prior=int(row['google_therapy_locations_used_in_score'])
        original=int(source['firstpass_clinical_title_lower_bound'])
        if prior<0 or original<0:
            raise RuntimeError('Negative Google clinical place count for '+code)
        population=int(row['population_5km_estimate_2021'])
        if population<=0:
            raise RuntimeError('Invalid five-kilometre population for '+code)
        # Different source queries may overlap. Max is a defensible lower bound.
        verified=max(prior,original)
        entry=dict(row)
        entry['firstpass_title_confirmed_clinical_places']=original
        entry['firstpass_google_businesses_geolocated']=int(source['original_google_located_businesses'])
        entry['firstpass_ambiguous_business_titles']=int(source['firstpass_ambiguous_titles'])
        entry['firstpass_nonclinical_business_titles']=int(source['firstpass_nonclinical_titles'])
        entry['firstpass_google_source_sha256']=source['firstpass_source_shard_sha256']
        entry['firstpass_website_query_status']=source['original_source_status']
        entry['confirmed_clinical_business_lower_bound']=verified
        entry['clinician_absence_proven']=False
        entry['clinically_audited_source_complete']=str(row['completed_source_feed']).lower()=='true'
        entry['clinical_businesses_per_10000_lower_bound']=round(verified*10000/population,8)
        entry['residents_per_clinical_business_upper_bound']=round(population/verified,2) if verified else ''
        entry['eligible_not_recent']=str(row['excluded_last_90_days']).lower()!='true' and code not in EXCLUDED_RECENT
        entry['ranking_status']='clinically_audited' if entry['clinically_audited_source_complete'] else 'uncertified_lower_bound'
        updated.append(entry)
    eligible=[r for r in updated if r['eligible_not_recent']]
    def sort_key(r):
        return (r['clinical_businesses_per_10000_lower_bound'],
                -int(r['population_5km_estimate_2021']),r['fsa'])
    candidates=sorted(eligible,key=sort_key)
    complete=[r for r in candidates if r['clinically_audited_source_complete']]
    if len(complete)>=60:
        cutoff=sorted(complete,key=sort_key)[59]['clinical_businesses_per_10000_lower_bound']
        contenders=[r for r in candidates if not r['clinically_audited_source_complete']
                    and r['clinical_businesses_per_10000_lower_bound']<=cutoff]
    else:
        cutoff=None
        contenders=[r for r in candidates if not r['clinically_audited_source_complete']]
    certified=bool(cutoff is not None and not contenders)
    dest.mkdir(parents=True,exist_ok=True)
    fields=list(updated[0])
    write_csv(dest/'Ontario_498_Actual_Clinical_Business_Evidence.csv',updated,fields)
    write_csv(dest/'Ontario_498_Unresolved_Clinical_Rank_Contenders.csv',contenders,fields)
    # This is deliberately named provisional: a low observed count could be
    # an incomplete search, Google ranking cap, or a truly sparse location.
    provisional=[dict(provisional_rank=i,**r) for i,r in enumerate(candidates[:60],1)]
    write_csv(dest/'Ontario_Provisional_60_By_Clinical_Lower_Bounds.csv',provisional,['provisional_rank']+fields)
    if certified:
        verified60=[dict(certified_rank=i,**r) for i,r in enumerate(sorted(complete,key=sort_key)[:60],1)]
        write_csv(dest/'Ontario_Certified_60_Within_Source_Model.csv',verified60,['certified_rank']+fields)
    report={
        'method':'Original per-business clinical Google Maps title classification plus independent rechecks; max rather than sum across overlapping searches',
        'all_498_fsas_reconciled':len(updated)==498,
        'clinically_confirmed_positive_firstpass_fsa_count':sum(int(r['firstpass_title_confirmed_clinical_places'])>0 for r in updated),
        'updated_clinical_lower_bounds_count':sum(int(r['firstpass_title_confirmed_clinical_places'])>int(r['google_therapy_locations_used_in_score']) for r in updated),
        'all_clinically_audited_eligible_sources':len(complete),
        'all_eligible_sources':len(eligible),
        'unresolved_rank_contenders':len(contenders),
        'cutoff_lower_density_per_10000':cutoff,
        'top_60_certified_within_source_model':certified,
        'proof_of_zero_therapists_anywhere':False,
        'warning':'A completed Google query or zero observed clinical listings cannot establish absence of therapists. The provisional 60 must not be used as a certified database list.',
        'checked_at_utc':datetime.now(timezone.utc).isoformat()}
    (dest/'Ontario_498_Clinical_Evidence_Integrated_Report.json').write_text(json.dumps(report,indent=2))
    print('ONTARIO_498_CLINICAL_EVIDENCE_INTEGRATED',json.dumps(report),flush=True)
    # Publication is fail-closed: no certified file is produced when false.
    # Source-audit success is independent of approval to publish a final list.
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--independent',required=True,type=Path)
    parser.add_argument('--original',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    analyze(args.independent,args.original,args.out)
