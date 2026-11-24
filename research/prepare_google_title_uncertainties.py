"""Make a bounded, provenance-preserving Google Maps category plan for
potentially high-opportunity FSA regions with unknown first-pass business titles.
The input is a *provisional* 60-area list. No zero-provider assertion is made.
"""
import argparse
import csv
import json
from pathlib import Path

from research.finalize_full_google_498 import clinical_title_classification


def prepare(firstpass: Path, provisional: Path, out: Path):
    original=json.loads(firstpass.read_text())['all_places_by_fsa']
    with provisional.open(newline='',encoding='utf8') as fh:
        candidates=list(csv.DictReader(fh))
    if len(original)!=498 or len(candidates)!=60 or len({r['fsa'] for r in candidates})!=60:
        raise RuntimeError('Expected complete 498-FSA places and 60 unique candidate regions')
    out.mkdir(parents=True,exist_ok=True)
    checkpoint=out/'checkpoints'
    checkpoint.mkdir(parents=True,exist_ok=True)
    report=[]
    seen_fsas=set()
    for position,row in enumerate(candidates,1):
        code=row['fsa']
        if code not in original or code in seen_fsas:
            raise RuntimeError('Invalid candidate from historic place observations: '+code)
        seen_fsas.add(code)
        places=original[code]
        if len({p['key'] for p in places})!=len(places):
            raise RuntimeError('Duplicate canonical Google places for '+code)
        clinical=sum(clinical_title_classification(p)=='clinical' for p in places)
        uncertain=sum(clinical_title_classification(p)=='ambiguous' for p in places)
        if int(row['firstpass_title_confirmed_clinical_places'])!=clinical:
            raise RuntimeError('Source classification changed unexpectedly: '+code)
        if int(row['firstpass_ambiguous_business_titles'])!=uncertain:
            raise RuntimeError('Source title ambiguity changed unexpectedly: '+code)
        doc={'fsa':code,'status':'original_firstpass_business_places',
             'source_runs':[44949320059,44949323771],
             'provisional_rank':position,
             'unique_observed_local_places':len(places),
             'local_places':places}
        (checkpoint/(code+'.json')).write_text(json.dumps(doc,indent=2))
        report.append({'fsa':code,'provisional_rank':position,'geolocated_places':len(places),
            'ambiguous_place_titles':uncertain,'source_confirmed_clinical_places':clinical})
    summary={'candidate_fsa_count':len(report),
        'geolocated_firstpass_places':sum(x['geolocated_places'] for x in report),
        'ambiguous_primary_google_categories_to_check':sum(x['ambiguous_place_titles'] for x in report),
        'fsas':report,'proven_zero_providers':False}
    (out/'plan.json').write_text(json.dumps(summary,indent=2))
    print('GOOGLE_CATEGORY_TARGET_PLAN',json.dumps({k:v for k,v in summary.items() if k!='fsas'}),flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--provisional',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    prepare(args.original,args.provisional,args.out)
