"""Single-process local dashboard, stable JSON protocol and background source tasks."""
from __future__ import annotations
import json, os, re, threading, traceback, webbrowser, socket, sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse,JSONResponse,FileResponse
from . import __version__,census,maps,psychology_today,housing,rank,state
from .common import ROOT,DATA,OUTPUT,LOGS,read_json,write_json,SourceUnavailable,InvalidEvidence,Incomplete,valid_fsa
app=FastAPI(title='Ontario Therapy Area Research',docs_url=None,redoc_url=None)
JOB_LOCK=threading.Lock()
CANCEL=threading.Event()

def error(exc,code=409):return JSONResponse({'ok':False,'error':str(exc)},status_code=code)

def status_payload():
    raw=state.read()
    # The dashboard polls frequently. Never send hundreds of complete therapist
    # profiles and map listings back on every poll; those live in evidence views.
    summary={'job':raw.get('job',{}),
             'areas':{fsa:{k:{'status':v.get('status'), 'error':v.get('error'),
                                  'at':v.get('at')} for k,v in rows.items()
                            if k in state.STAGES and isinstance(v,dict)}
                      for fsa,rows in raw.get('areas',{}).items()},
             'events':raw.get('events',[])[-40:]}
    return {'ok':True,'version':__version__,'state':summary,'census':census_health(),
            'busy':JOB_LOCK.locked(),'google_engine_installed':maps.binary().is_file()}

def census_health():
    return {'fsa_population':(DATA/'fsa_population.json').is_file(),
            'da_population':(DATA/'da_population.json').is_file(),
            'fsa_boundaries':(DATA/'fsa_boundaries.json').is_file(),
            'ready':all((DATA/p).is_file() for p in ('fsa_population.json','da_population.json','fsa_boundaries.json'))}

def start_job(label,fn):
    if not JOB_LOCK.acquire(blocking=False):raise Incomplete('A task is already running. See the live status; the previous search is preserved.')
    CANCEL.clear()
    state.job('running',label)
    state.event('Starting '+label)
    def worker():
        try:
            fn()
            if CANCEL.is_set():raise Incomplete('Stopped after current stage; progress saved. Press Resume to continue.')
            state.job('complete',label+' finished')
            state.event('Finished '+label)
        except Exception as exc:
            (LOGS/'last_error.log').write_text(traceback.format_exc(),encoding='utf8')
            state.job('failed',str(exc),error_type=exc.__class__.__name__)
            state.event('ERROR '+str(exc))
        finally:
            JOB_LOCK.release()
    threading.Thread(target=worker,name='therapy-research-worker',daemon=True).start()

def progress(message):state.progress(message)

def census_setup():
    for label,task in (('postal-area population',lambda:census.load_population('fsa',progress)),
                       ('small-area population',lambda:census.load_population('da',progress)),
                       ('postal-area boundaries',lambda:census.fsa_geometry(progress))):
        if CANCEL.is_set():return
        progress('Validating official census source: '+label)
        result=task()
        state.event(f'Validated {label}: {len(result)} records')
    if not census_health()['ready']:raise Incomplete('Census job ended without all required sources')


def do_population(fsa,geom):
    population=census.load_population('da')
    areas=census.da_near(fsa,geom,progress)
    centre=census.representative(geom)
    catch=census.catchment(*centre,areas,population)
    catch.update({'center':centre,'fsa':fsa,'source_url':census.DA_URL})
    state.stage(fsa,'population','verified',catch)
    return catch

def do_google(fsa,geom):
    results=maps.execute(fsa,geom,progress,cancel_requested=CANCEL.is_set)
    centre=census.representative(geom)
    n=len(rank.nearby(results['locations'],*centre,5))
    results['within_5km_of_fsa_point']=n
    if not n:raise InvalidEvidence('No Google businesses located within 5km of FSA candidate. Cannot infer zero competition.')
    # Native job succeeded, records are geolocated; still require independent source review.
    state.stage(fsa,'google','review_required',results)
    return results

def do_pt(fsa):
    result=psychology_today.collect(fsa,progress,cancel_requested=CANCEL.is_set)
    state.stage(fsa,'psychology_today','review_required',result)
    return result

def do_housing(fsa,geom,auto_vision=False):
    da=census.da_near(fsa,geom,progress)
    pop=census.load_population('da')
    points=housing.sample_points(geom,da,pop,limit=24)
    if len(points)<6:raise InvalidEvidence(f'{fsa}: fewer than six residential DA sample points')
    report=housing.capture(fsa,points,progress,max_usable=8,minimum_usable=6,cancel_requested=CANCEL.is_set)
    if auto_vision:
        if not housing.vision_available():
            raise SourceUnavailable('Local vision model unavailable. Install Ollama and qwen2.5vl:3b or classify images manually in the dashboard.')
        changed=False
        for s in report['samples']:
            if s['status']=='captured_pending_review' and not s.get('vision'):
                s['vision']=housing.classify(s['image']);changed=True
                write_json(DATA/'areas'/fsa/'housing'/'manifest.json',report)
        if changed:state.event(f'{fsa} classified housing images using local model')
    state.stage(fsa,'housing','review_required',report)
    return report

def process_area(fsa,auto_vision=False):
    geos=census.fsa_geometry()
    if fsa not in geos:raise InvalidEvidence(f'{fsa} was not found in official 2021 Ontario FSA boundaries')
    geom=geos[fsa]
    jobs=(('population',lambda:do_population(fsa,geom)),('google',lambda:do_google(fsa,geom)),
          ('psychology_today',lambda:do_pt(fsa)),('housing',lambda:do_housing(fsa,geom,auto_vision)))
    failures=[]
    for name,work in jobs:
        if CANCEL.is_set():break
        existing=state.read()['areas'].get(fsa,{}).get(name,{})
        if existing.get('status') in ('verified','review_required'):continue
        state.stage(fsa,name,'running',existing.get('evidence'))
        state.progress(f'{fsa}: collecting {name}')
        try:work()
        except Exception as exc:
            failures.append(f'{fsa}/{name}: {exc}')
            record=state.read()['areas'][fsa].get(name,{})
            state.stage(fsa,name,'failed',record.get('evidence'),str(exc))
            state.event(f'FAILED {fsa}/{name}: {exc}')
    return failures

def research_selected(codes,auto_vision=False):
    if not census_health()['ready']:raise Incomplete('Download and validate census data first')
    errors=[]
    for i,fsa in enumerate(codes):
        if CANCEL.is_set():break
        progress(f'Area {i+1}/{len(codes)}: {fsa}')
        errors.extend(process_area(fsa,auto_vision))
    if errors:raise Incomplete(f'{len(errors)} required source job(s) remain incomplete. '+ '; '.join(errors[:5]))

@app.get('/')
def home():return HTMLResponse((ROOT/'web'/'index.html').read_text(encoding='utf8'))
@app.get('/health')
def health():return {'ok':True,'version':__version__,'census':census_health(),'busy':JOB_LOCK.locked()}
@app.get('/api/status')
def get_status():return status_payload()
@app.post('/api/census')
def download_census():
    try:start_job('Download official Statistics Canada census sources',census_setup)
    except Exception as exc:return error(exc)
    return {'ok':True,'message':'Started. Follow the progress shown directly under this button.'}
@app.get('/api/eligible')
def eligible(radius_km:float=125,min_population:int=12000):
    try:
        if not census_health()['ready']:raise Incomplete('Census data are missing. Complete the first step before listing areas.')
        if not 12<=radius_km<=1500 or not 0<=min_population<=1000000:raise InvalidEvidence('Invalid radius or population filter')
        found=census.areas_near_hamilton(radius_km,min_population)
        return {'ok':True,'count':len(found),'areas':found}
    except Exception as exc:return error(exc)
@app.post('/api/run')
async def run(request:Request):
    try:
        j=await request.json()
        codes=list(dict.fromkeys(x.strip().upper() for x in str(j.get('areas','')).split(',') if x.strip()))
        if not codes or len(codes)>800 or any(not valid_fsa(x) for x in codes):
            raise InvalidEvidence('Specify 1–800 valid three-character Ontario postal areas, separated by commas')
        if not census_health()['ready']:raise Incomplete('Complete official census data setup before searching')
        auto_vision=bool(j.get('auto_vision',False))
        start_job('Collect '+str(len(codes))+' postal areas',lambda:research_selected(codes,auto_vision))
        return {'ok':True,'message':f'Searching {len(codes)} areas; all four required source stages will be checked.'}
    except Exception as exc:return error(exc)
@app.post('/api/stop')
def stop():
    CANCEL.set()
    return {'ok':True,'message':'Stop requested. The current external collection may have to finish first. Progress is saved.'}
@app.get('/api/evidence/{code}/{source}')
def evidence(code:str,source:str):
    if not valid_fsa(code) or source not in state.STAGES:return error(InvalidEvidence('Unknown area or source'),404)
    row=state.read().get('areas',{}).get(code,{}).get(source)
    if row is None:return error(Incomplete('No evidence for this stage yet'),404)
    if source=='psychology_today' and row.get('evidence'):
        ev=row['evidence']
        row['evidence']={k:v for k,v in ev.items() if k!='profiles'}
        row['evidence']['unclassified_profiles']=[{k:p.get(k) for k in ('id','name','url','kind')} for p in ev.get('profiles',[]) if p.get('kind')=='unknown']
    if source=='google' and row.get('evidence'):
        row['evidence']={k:v for k,v in row['evidence'].items() if k!='locations'}
    return {'ok':True,'record':row}
@app.post('/api/photo-review')
async def photo_review(request:Request):
    try:
        j=await request.json();fsa=str(j.get('fsa','')).upper()
        if not valid_fsa(fsa):raise InvalidEvidence('Invalid postal area')
        found=housing.mark_review(fsa,str(j.get('uid','')),str(j.get('category','')),str(j.get('note','')))
        row=state.read()['areas'].get(fsa,{}).get('housing',{})
        if row.get('status')=='review_required':
            manifest=read_json(DATA/'areas'/fsa/'housing'/'manifest.json')
            state.stage(fsa,'housing','review_required',manifest)
        return {'ok':True,'message':f'Photo for {found["point"]["id"]} reviewed.'}
    except Exception as ex:return error(ex)
@app.post('/api/pt-profile-review')
async def pt_profile_review(request:Request):
    try:
        j=await request.json()
        code=str(j.get('fsa','')).upper();uid=str(j.get('id',''))
        kind=str(j.get('kind',''));note=str(j.get('note','')).strip()
        allowed={'local_postal_listing','online_only','serves_area'}
        if not valid_fsa(code) or not uid.isdigit() or kind not in allowed or len(note)<10:
            raise InvalidEvidence('Choose a valid PT classification, profile ID and observation')
        record=state.read().get('areas',{}).get(code,{}).get('psychology_today',{})
        if record.get('status')!='review_required':raise InvalidEvidence('PT directory must first be collected and awaiting review')
        ev=record['evidence'];profile=next((p for p in ev.get('profiles',[]) if str(p.get('id'))==uid),None)
        if not profile:raise InvalidEvidence('PT profile not present in source evidence')
        profile['kind']=kind
        profile['manual_review']={'kind':kind,'note':note,'profile_url':profile['url']}
        ev['classes']={k:sum(p['kind']==k for p in ev['profiles']) for k in
               ('local_postal_listing','online_only','serves_area','unknown')}
        write_json(DATA/'areas'/code/'pt'/'result.json',ev)
        state.stage(code,'psychology_today','review_required',ev)
        return {'ok':True,'message':f'Profile {uid} classified as {kind}. Unknown remaining: {ev["classes"]["unknown"]}.'}
    except Exception as exc:return error(exc)

@app.post('/api/approve')
async def approve(request:Request):
    try:
        j=await request.json();fsa=str(j.get('fsa','')).upper();source=str(j.get('source',''))
        note=str(j.get('note','')).strip()
        if not valid_fsa(fsa) or source not in ('google','psychology_today','housing'):
            raise InvalidEvidence('Unknown area or source')
        if len(note)<15:raise InvalidEvidence('Describe the source evidence you checked in at least 15 characters')
        row=state.read().get('areas',{}).get(fsa,{}).get(source,{})
        if row.get('status')!='review_required' or not row.get('evidence'):
            raise InvalidEvidence('This stage has no complete source collection awaiting review')
        ev=row['evidence']
        if source=='google':
            if not ev.get('locations') or ev.get('unlocated'):raise InvalidEvidence('Google evidence incomplete')
        if source=='psychology_today':
            if ev['unique_profiles']<ev['directory_total']['lower_bound']:
                raise InvalidEvidence('Psychology Today profile count below stated directory total')
            if ev['classes']['unknown']>0:
                raise InvalidEvidence(f'{ev["classes"]["unknown"]} PT profiles still have unknown local/online classification. Classify each profile in the evidence panel.')
        if source=='housing':
            report=read_json(DATA/'areas'/fsa/'housing'/'manifest.json')
            if housing.count_reviewed(report)<6:
                raise InvalidEvidence(f'Only {housing.count_reviewed(report)} of six required housing photographs are classified. Review each image below.')
            ev=report
        ev['human_source_review']={'note':note}
        state.stage(fsa,source,'verified',ev)
        return {'ok':True,'message':f'Approved {fsa}/{source}. Evidence saved.'}
    except Exception as ex:return error(ex)
@app.post('/api/rank')
async def make_rank(request:Request):
    try:
        j=await request.json()
        codes=list(dict.fromkeys(x.strip().upper() for x in str(j.get('areas','')).split(',') if x.strip()))
        if not codes or any(not valid_fsa(x) for x in codes):raise InvalidEvidence('Enter valid Ontario postal areas')
        if JOB_LOCK.locked():raise Incomplete('Wait for collection to finish before producing the ranking')
        report=rank.analyse(codes)
        return {'ok':True,'rows':report['rows'],'two':report['two'],
                'files':['output/postal_area_comparison.csv','output/candidate_locations.csv','output/results.json']}
    except Exception as exc:return error(exc)
@app.get('/api/map/{code}')
def area_map(code:str):
    try:
        code=code.upper()
        if not valid_fsa(code):raise InvalidEvidence('Invalid postal area')
        geo=census.fsa_geometry()
        if code not in geo:raise InvalidEvidence('Unknown census FSA')
        google=read_json(DATA/'areas'/code/'google'/'locations.json',{'locations':[]})
        return {'ok':True,'fsa':code,'center':census.representative(geo[code]),
                'geometry':geo[code],'locations':google['locations']}
    except Exception as ex:return error(ex)
@app.get('/api/photo/{code}/{uid}')
def serve_photo(code:str,uid:str):
    code=code.upper()
    if not valid_fsa(code) or not re.fullmatch(r'\d{8}',uid):
        return error(InvalidEvidence('Invalid housing photo reference'),404)
    folder=DATA/'areas'/code/'housing'
    report=read_json(folder/'manifest.json',{})
    sample=next((s for s in report.get('samples',[]) if str(s.get('point',{}).get('id'))==uid),None)
    if not sample or sample.get('status')!='captured_pending_review':
        return error(Incomplete('Housing photo has not been captured'),404)
    filename=sample.get('image')
    if not filename:return error(Incomplete('Missing housing photograph'),404)
    path=Path(filename).resolve()
    if folder.resolve() not in path.parents or path.suffix.lower()!='.png' or not path.is_file():
        return error(InvalidEvidence('Housing image is unavailable or outside its evidence folder'),404)
    return FileResponse(path,media_type='image/png')

@app.get('/data/{file_path:path}')
def serve_data(file_path:str):
    path=(ROOT/file_path).resolve()
    # Grant only data evidence photographs and generated results, never profiles/logs.
    within_data=DATA.resolve() in path.parents and path.suffix.lower()=='.png'
    within_output=OUTPUT.resolve() in path.parents and path.suffix.lower() in ('.csv','.json')
    if not ((within_data or within_output) and path.is_file()):return error(InvalidEvidence('Not a public result file'),404)
    return FileResponse(path)

def free_port(preferred=8765):
    with socket.socket() as s:
        try:s.bind(('127.0.0.1',preferred));return preferred
        except OSError:pass
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]

def main():
    import uvicorn
    state.mark_interrupted_jobs()
    port=free_port()
    print(f'Ontario Therapy Area Finder v{__version__}\nDashboard: http://127.0.0.1:{port}/\nKeep this Terminal open.\n',flush=True)
    threading.Timer(1.5,lambda:webbrowser.open(f'http://127.0.0.1:{port}/?version={__version__}')).start()
    uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')
if __name__=='__main__':main()
