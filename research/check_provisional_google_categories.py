"""Review ambiguous Google Maps business categories in reproducible shards.
Safeguard: original name, coordinates, URL and ID are never overwritten.
Google challenge and unknown category remain explicit uncertainty.
"""
import argparse
import json
import shutil
from pathlib import Path
from research.enrich_google_categories import enrich
from research.finalize_full_google_498 import clinical_title_classification


def run(input_dir:Path, output_dir:Path, shard:int, shards:int, seconds:int):
    if not 0<=shard<shards or shards!=12 or not 60<=seconds<=600:
        raise RuntimeError('Expected twelve bounded source-check shards')
    plan=json.loads((input_dir/'plan.json').read_text())
    entries=plan['fsas']
    if len(entries)!=60 or len({x['fsa'] for x in entries})!=60:
        raise RuntimeError('Expected 60 unique original business-check categories')
    output_dir.mkdir(parents=True,exist_ok=True)
    reports=[]
    for i,entry in enumerate(entries):
        if i%shards!=shard:
            continue
        code=entry['fsa']
        original=input_dir/'checkpoints'/(code+'.json')
        dest=output_dir/(code+'.json')
        if not original.is_file():
            raise RuntimeError('No original Google business place checkpoint '+code)
        if not dest.is_file():
            shutil.copy2(original,dest)
        before=json.loads(original.read_text())
        current=json.loads(dest.read_text())
        if before['fsa']!=code or current['fsa']!=code:
            raise RuntimeError('Google FSA source identity changed '+code)
        source_keys={p['key'] for p in before['local_places']}
        present_keys={p['key'] for p in current['local_places']}
        if source_keys!=present_keys:
            raise RuntimeError('Google category fetch lost or added source businesses '+code)
        report=enrich(dest,max_seconds=seconds)
        after=json.loads(dest.read_text())
        if {p['key'] for p in after['local_places']}!=source_keys:
            raise RuntimeError('Source Google places changed while category-checking '+code)
        for prior,new in zip(before['local_places'],after['local_places']):
            if any(prior.get(f)!=new.get(f) for f in ('key','name','lat','lon','source_url')):
                raise RuntimeError('Google category audit altered place location identity '+code)
        unresolved=sum(clinical_title_classification(p)=='ambiguous' for p in after['local_places'])
        reports.append({'fsa':code,'status':'challenge' if report['google_access_restricted'] else 'checked',
          'ambiguous_businesses_remaining':unresolved,'new_category_pages_checked':report['new_category_pages_checked']})
        print('PROVISIONAL_FSA_GOOGLE_CATEGORY_RESULT',json.dumps(reports[-1]),flush=True)
        (output_dir/'progress.json').write_text(json.dumps(reports,indent=2))
        if report['google_access_restricted']:
            print('GOOGLE_SOURCE_RESTRICTED_STOP_THIS_SHARD',shard,code,flush=True)
            break
    return reports


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--shard',type=int,required=True)
    p.add_argument('--shards',type=int,default=12)
    p.add_argument('--seconds-per-fsa',type=int,default=420)
    args=p.parse_args()
    run(args.input,args.out,args.shard,args.shards,args.seconds_per_fsa)
