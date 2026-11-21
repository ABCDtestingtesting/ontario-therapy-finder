"""Unattended external-source smoke tests; failures are test failures, never zero counts.

Runs only when --live is supplied; each stage has its own timeout in the CI workflow.
Outputs diagnostic JSON but never stores client information or credentials.
"""
import argparse, json, os, pathlib, subprocess, sys, traceback
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'live_reports';OUT.mkdir(exist_ok=True)
os.environ.setdefault('THERAPY_HEADLESS','1')
os.environ.setdefault('THERAPY_UNATTENDED','1')

def run_stage(stage):
    if stage=='census':
        from finder import census
        fsa=census.load_population('fsa')
        da=census.load_population('da')
        boundaries=census.fsa_geometry()
        assert 'L7A' in fsa and 'L7A' in boundaries, 'L7A missing from official census data'
        assert len(da)>10000 and len(boundaries)>300
        return {'fsa_records':len(fsa),'da_records':len(da),'boundary_records':len(boundaries),'L7A_population_2021':fsa['L7A']['population']}
    if stage=='maps':
        from finder import maps
        exe=maps.ensure_binary(print)
        assert maps.command_works(exe), 'Scraper CLI selfcheck failed'
        folder=OUT/'google';folder.mkdir(exist_ok=True)
        queries=folder/'queries.txt';queries.write_text('psychotherapist\n')
        output=folder/'raw.csv'
        # Deliberately small pilot cell. A complete region-wide search is a later separate test.
        cmd=[str(exe),'-input',str(queries),'-results',str(output),'-grid-bbox',
             '43.728,-79.820,43.738,-79.808','-grid-cell','1.0','-zoom','16','-depth','3','-c','1']
        with (folder/'collector.txt').open('w') as log:
            p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        assert p.returncode==0, f'Collector exited {p.returncode}; see collector.txt'
        assert output.exists() and output.stat().st_size>30, 'No Google Maps CSV data'
        result=maps.parse_csv(output)
        assert result['raw_rows']>0 and result['locations'], 'No verified Google Maps listings'
        return {'binary':str(exe),'raw_rows':result['raw_rows'],'locations':len(result['locations']),'duplicates':result['duplicates']}
    if stage=='psychology_today':
        from finder import psychology_today as pt
        result=pt.collect('L7A',progress=print,max_pages=15)
        assert result['unique_profiles']>=result['directory_total']['lower_bound']
        return {'profiles':result['unique_profiles'],'pages':len(result.get('pages',[])),'classes':result.get('classes')}
    if stage=='housing':
        from finder import housing
        pts=[{'id':'SAMPLE1','lat':43.7315,'lon':-79.8143,'occupied_dwellings_da_2021':1}]
        result=housing.capture('L7A',pts,progress=print,max_usable=1,minimum_usable=1)
        images=[x for x in result['samples'] if x['status']=='captured_pending_review']
        assert images and housing.screenshot_is_nonblank(images[0]['image']), 'No usable screenshot captured'
        # This confirms browser screenshot capture ONLY. Visual housing classification needs separate review.
        return {'screenshots':len(images),'photo_review':'required'}
    raise ValueError('Unknown stage: '+stage)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',required=True,choices=['census','maps','psychology_today','housing'])
    parser.add_argument('--live',action='store_true',help='Explicitly allow network source tests')
    args=parser.parse_args()
    if not args.live:parser.error('Live network probes require --live')
    report={'stage':args.stage,'timestamp':datetime.now(timezone.utc).isoformat(),'status':'failed'}
    try:
        report['evidence']=run_stage(args.stage)
        report['status']='passed'
    except Exception as exc:
        report['error']=str(exc)
        report['traceback']=traceback.format_exc()[-5000:]
        traceback.print_exc()
    finally:
        (OUT/(args.stage+'.json')).write_text(json.dumps(report,indent=2))
        print(json.dumps({k:v for k,v in report.items() if k!='traceback'},indent=2))
    sys.exit(0 if report['status']=='passed' else 1)
