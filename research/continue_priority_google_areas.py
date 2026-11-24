"""Select and resume only still-viable 5-km Ontario Google clinical sources.
Every preserved business must retain its original evidence; challenged and
capped results stay pending. Does not use Psychology Today or claim provider
absence.
"""
from __future__ import annotations
import argparse,csv,json,shutil,time
from pathlib import Path
from playwright.sync_api import sync_playwright
from research.recover_google_tiles import run_area
from research import google_measured_recenter_runner
from finder import google_browser

def load_plan(audit:Path,size:int):
    with audit.open(newline='',encoding='utf8') as fh: rows=list(csv.DictReader(fh))
    if len(rows)!=498 or len({r['fsa'] for r in rows})!=498:
        raise RuntimeError('All 498 unique Ontario FSA audit records required')
    possible=[r for r in rows if r['previously_screened_excluded']=='False'
              and r['merged_google_observation_source_complete']=='False']
    if len(possible)<size:raise RuntimeError('Fewer than requested potentially ranking FSA sources')
    possible.sort(key=lambda r:(float(r['observed_clinical_offices_per_10000_lower_bound']),
                                -int(r['population_within_5km_2021_estimate']),r['fsa']))
    return possible[:size]

def find_seed(code:str,archive:Path):
    paths=list(archive.glob('**/'+code+'.json'))
    if len(paths)>1:
        raise RuntimeError('Duplicate historical Google checkpoint for '+code)
    if not paths:return None
    doc=json.loads(paths[0].read_text())
    if doc.get('fsa')!=code:raise RuntimeError('Historical Google place identity mismatch '+code)
    if len({p['key'] for p in doc.get('local_places',[])})!=len(doc.get('local_places',[])):
        raise RuntimeError('Duplicate historical place IDs '+code)
    return paths[0]

def run(audit:Path,archive:Path,shard:int,shards:int,cohort:int,out:Path,seconds:int):
    if not 0<=shard<shards or not 1<=cohort<=498 or not 90<=seconds<=1500:
        raise RuntimeError('Invalid bounded Google source batch')
    rank=load_plan(audit,cohort)
    selected=[r for i,r in enumerate(rank) if i%shards==shard]
    area_doc=json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())
    areas={r['fsa']:r for r in area_doc['areas']}
    if len(areas)!=498 or any(r['fsa'] not in areas for r in selected):
        raise RuntimeError('Google research census geography missing')
    out.mkdir(parents=True,exist_ok=True)
    snapshot=out/'checkpoints'
    snapshot.mkdir(exist_ok=True)
    records=[]
    google_browser._refresh_map_area_results=google_measured_recenter_runner.refresh
    with sync_playwright() as pw:
        browser=pw.firefox.launch_persistent_context(
            str(out/'firefox-profile'),headless=True,
            viewport={'width':1400,'height':960},locale='en-CA')
        try:
            for candidate in selected:
                code=candidate['fsa']
                root=snapshot/code
                root.mkdir(parents=True,exist_ok=True)
                target=root/(code+'.json')
                old=find_seed(code,archive)
                if old and not target.exists():
                    shutil.copy2(old,target)
                if target.is_file():
                    before=json.loads(target.read_text())
                    if before.get('fsa')!=code:
                        raise RuntimeError('Wrong loaded FSA identity '+code)
                    source_center=before.get('center')
                    expected=[areas[code]['lat'],areas[code]['lon']]
                    if source_center and max(abs(float(a)-float(b)) for a,b in zip(source_center,expected))>0.00001:
                        raise RuntimeError('Google FSA source map centre differs from official 2021 census '+code)
                enriched=dict(areas[code],ranking_cutoff=0.00000001,
                    population_5km_estimate=int(candidate['population_within_5km_2021_estimate']),
                    baseline_observed_5km=0)
                start=time.monotonic()
                try:
                    result=run_area(browser,enriched,root,seconds)
                    status=result.get('status')
                    summary={'fsa':code,'status':status,
                      'complete_tiles':result.get('completed_coverage_tiles',0),
                      'total_tiles':result.get('total_coverage_tiles',18),
                      'capped_tiles':result.get('capped_leaf_tiles'),
                      'pending_queries':len(result.get('pending',[])),
                      'observed_unique_businesses':result.get('unique_observed_local_places'),
                      'unlocated_links':result.get('unresolved_leaf_links'),
                      'elapsed_s':round(time.monotonic()-start,1)}
                except Exception as error:
                    summary={'fsa':code,'status':'exception_with_saved_checkpoint',
                        'exception':str(error)[:400],
                        'elapsed_s':round(time.monotonic()-start,1)}
                records.append(summary)
                (out/'progress.json').write_text(json.dumps(records,indent=2))
                print('GOOGLE_PRIORITY_FSA_RESEARCH',json.dumps(summary),flush=True)
                # A Google verification challenge blocks this browser session.
                # Preserve the remaining locations as explicitly pending
                # instead of interpreting them as zero clinics.
                if summary.get('status')=='access_restricted':
                    break
        finally:
            browser.close()
    report={'planned_fsa_count':len(selected),'attempted':len(records),
            'fully_verified_tiles_sources':sum(r['status']=='verified_tile_feed' for r in records),
            'incomplete':sum(r['status']!='verified_tile_feed' for r in records),
            'source_results':records}
    (out/'result.json').write_text(json.dumps(report,indent=2))
    print('GOOGLE_PRIORITY_SHARD_REPORT',json.dumps({k:v for k,v in report.items() if k!='source_results'}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--audit',type=Path,required=True)
    p.add_argument('--seeds',type=Path,required=True)
    p.add_argument('--shard',type=int,required=True)
    p.add_argument('--shards',type=int,default=15)
    p.add_argument('--cohort',type=int,default=90)
    p.add_argument('--seconds',type=int,default=360)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    run(a.audit,a.seeds,a.shard,a.shards,a.cohort,a.out,a.seconds)
