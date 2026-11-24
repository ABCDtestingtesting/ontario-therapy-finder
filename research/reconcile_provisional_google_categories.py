"""Integrate verified Google primary business categories for provisional
Ontario top-60 candidates, preserving exact place IDs and missing evidence.
This is a lower-bound refinement; absent/unobserved clinicians stay unknown.
"""
import argparse
import csv
import json
from datetime import datetime,timezone
from pathlib import Path
from research.finalize_full_google_498 import clinical_title_classification

EXCLUDE={'L6Z','L7A','L6X','L6R','N1T','N3S','P5N','N4W'}

def read_csv(path):
    with path.open(newline='',encoding='utf8') as fh:
        return list(csv.DictReader(fh))

def write_csv(path,rows,fields):
    with path.open('w',newline='',encoding='utf8') as fh:
        writer=csv.DictWriter(fh,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

def run(full_audit:Path,raw_source:Path,plan_path:Path,category_root:Path,out_dir:Path):
    base=read_csv(full_audit)
    raw=json.loads(raw_source.read_text())['all_places_by_fsa']
    plan=json.loads(plan_path.read_text())['fsas']
    if len(base)!=498 or len({r['fsa'] for r in base})!=498:
        raise RuntimeError('Missing complete 498-area audited evidence')
    if len(raw)!=498 or len(plan)!=60 or len({r['fsa'] for r in plan})!=60:
        raise RuntimeError('Missing complete original Google source or 60 candidates')
    codes={r['fsa'] for r in plan}
    checks={}
    for f in category_root.glob('**/[A-Z][0-9][A-Z].json'):
        code=f.stem
        if code not in codes or code in checks:
            raise RuntimeError('Duplicate or unauthorized candidate category checkpoint '+code)
        checkpoint=json.loads(f.read_text())
        if checkpoint['fsa']!=code:
            raise RuntimeError('Wrong source identity '+code)
        original={p['key']:p for p in raw[code]}
        places=checkpoint['local_places']
        if len(places)!=len(original) or {p['key'] for p in places}!=set(original):
            raise RuntimeError('Google category review changed source place keys for '+code)
        for p in places:
            prev=original[p['key']]
            for prop in ('name','lat','lon','source_url'):
                if p.get(prop)!=prev.get(prop):
                    raise RuntimeError('Google category fetch changed original place '+code)
        checks[code]=places
    updated=[]
    changed=0
    new_clinical=0
    missed=[]
    for row in base:
        r=dict(row)
        code=r['fsa']
        prior=int(r['confirmed_clinical_business_lower_bound'])
        if code in codes:
            entries=checks.get(code)
            if entries is None:
                missed.append(code)
                entries=raw[code]
            firstpass=sum(clinical_title_classification(p)=='clinical' for p in entries)
            remaining=sum(clinical_title_classification(p)=='ambiguous' for p in entries)
            r['category_audited_places']=len(entries) if code in checks else 0
            r['remaining_ambiguous_google_place_categories']=remaining
            r['verified_firstpass_clinical_after_detail_lookup']=firstpass
            new=max(prior,firstpass)
            if new>prior:
                changed+=1
                new_clinical+=new-prior
        else:
            new=prior
            r['category_audited_places']=''
            r['remaining_ambiguous_google_place_categories']=''
            r['verified_firstpass_clinical_after_detail_lookup']=''
        r['confirmed_clinical_business_lower_bound']=new
        pop=int(r['population_5km_estimate_2021'])
        r['clinical_businesses_per_10000_lower_bound']=round(new*10000/pop,8)
        r['residents_per_clinical_business_upper_bound']=round(pop/new,2) if new else ''
        # Checking a business category is not a geographically complete census.
        r['clinician_absence_proven']=False
        updated.append(r)
    eligible=[r for r in updated if str(r['excluded_last_90_days']).lower()!='true' and r['fsa'] not in EXCLUDE]
    rank=lambda r:(float(r['clinical_businesses_per_10000_lower_bound']),
                   -int(r['population_5km_estimate_2021']),r['fsa'])
    ranked=sorted(eligible,key=rank)
    completed=[r for r in ranked if str(r['clinically_audited_source_complete']).lower()=='true']
    cutoff=sorted(completed,key=rank)[59]['clinical_businesses_per_10000_lower_bound'] if len(completed)>=60 else None
    still_unresolved=([r for r in ranked if
      str(r['clinically_audited_source_complete']).lower()!='true'
      and (cutoff is None or float(r['clinical_businesses_per_10000_lower_bound'])<=cutoff)])
    certified=cutoff is not None and not still_unresolved
    out_dir.mkdir(parents=True,exist_ok=True)
    fields=list(updated[0])
    write_csv(out_dir/'Ontario_498_After_Primary_Category_Checks.csv',updated,fields)
    write_csv(out_dir/'Ontario_Unresolved_Rank_Contenders.csv',still_unresolved,fields)
    write_csv(out_dir/'Ontario_New_Provisional_Top60.csv',
              [dict(provisional_rank=i,**r) for i,r in enumerate(ranked[:60],1)],['provisional_rank']+fields)
    if certified:
        write_csv(out_dir/'Ontario_Certified_60_Within_Google_Observation_Model.csv',
                  [dict(rank=i,**r) for i,r in enumerate(completed[:60],1)],['rank']+fields)
    source_original=set(codes)
    source_new={r['fsa'] for r in ranked[:60]}
    report={
       'google_category_source_checkpoints_present':len(checks),
       'provisional_60_category_fsa_missing':sorted(missed),
       'new_positively_identified_clinical_fsa_count':changed,
       'additional_verified_clinical_lower_bound_places':new_clinical,
       'top_60_candidate_fsas_changed':len(source_original^source_new)//2,
       'new_unchecked_top_60_candidates':sorted(source_new-source_original),
       'clinically_audited_eligible_fsa_count':len(completed),
       'eligible_uncertified_rank_contenders':len(still_unresolved),
       'final_60_source_model_certified':certified,
       'proved_zero_therapists_anywhere':False,
       'checked_at_utc':datetime.now(timezone.utc).isoformat()}
    (out_dir/'Ontario_Category_Review_Integration_Report.json').write_text(json.dumps(report,indent=2))
    print('GOOGLE_CATEGORIES_RECONCILED_WITH_498',json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('full','raw','plan','categories','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    run(args.full,args.raw,args.plan,args.categories,args.out)
