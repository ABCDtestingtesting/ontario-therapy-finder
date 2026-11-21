"""Repeatable street-image sampling with image content checks and optional local AI.

A screenshot is not automatically proof that housing was visible. The dashboard
requires each image to be visually reviewed or classified with verified model output.
"""
from __future__ import annotations
import base64, json, math, re, os
from pathlib import Path
from urllib.parse import urlencode
import requests
from PIL import Image,ImageStat
from shapely.geometry import shape
from shapely.ops import transform
from playwright.sync_api import sync_playwright
from .common import DATA,write_json,read_json,SourceUnavailable,InvalidEvidence
from .census import project,unproject
MODEL='qwen2.5vl:3b'
LABELS=('detached','semi-detached','townhouse','low-rise apartments','mid-rise apartments',
        'high-rise apartments','mixed housing','undeveloped','unknown')
RESIDENTIAL_LABELS=frozenset(LABELS)-{'undeveloped','unknown'}

def street_url(lat,lon,heading=90):
    return 'https://www.google.com/maps/@?'+urlencode({'api':'1','map_action':'pano',
                  'viewpoint':f'{lat:.6f},{lon:.6f}','heading':heading,'pitch':0,'fov':90})

def sample_points(fsa_geo,da_geos,da_people,limit=22,min_gap=350):
    area=transform(project(),shape(fsa_geo));candidates=[]
    for uid,geo in da_geos.items():
        row=da_people.get(uid)
        if not row or row['occupied']<=0:continue
        overlap=area.intersection(transform(project(),shape(geo)))
        if overlap.is_empty or overlap.area<50:continue
        p=overlap.representative_point()
        # Choose more populated DAs, with a geographic exclusion to prevent clustering.
        candidates.append((row['occupied'],uid,p))
    candidates.sort(key=lambda p:(-p[0],p[1]))
    chosen=[]
    for homes,uid,p in candidates:
        if any(p.distance(q[2])<min_gap for q in chosen):continue
        chosen.append((homes,uid,p))
        if len(chosen)>=limit:break
    result=[]
    for homes,uid,p in chosen:
        lon,lat=unproject()(p.x,p.y)
        result.append({'id':uid,'lat':round(lat,6),'lon':round(lon,6),'occupied_dwellings_da_2021':homes})
    return result

def screenshot_is_nonblank(path):
    try:
        with Image.open(path) as im:
            if im.width<900 or im.height<500:return False
            img=im.convert('RGB').resize((120,70))
            stats=ImageStat.Stat(img)
            return sum(stats.stddev)>28
    except (OSError,ValueError):return False

def capture(fsa,points,progress=lambda s:None,max_usable=8,minimum_usable=6,context_factory=None,cancel_requested=lambda:False):
    folder=DATA/'areas'/fsa/'housing';folder.mkdir(parents=True,exist_ok=True)
    manifest=read_json(folder/'manifest.json',{'samples':[]})
    existing={s['point']['id']:s for s in manifest['samples']}
    if cancel_requested():
        raise SourceUnavailable('Housing image scan stopped before starting; saved photographs preserved')
    with sync_playwright() as pw:
        context=(context_factory(pw) if context_factory else
            pw.firefox.launch_persistent_context(str(folder/'firefox_profile'),
                                                viewport={'width':1365,'height':880},
                                                headless=os.environ.get('THERAPY_HEADLESS')=='1'))
        page=context.pages[0] if context.pages else context.new_page()
        try:
            for idx,point in enumerate(points):
                if cancel_requested():
                    raise SourceUnavailable('Housing image scan stopped by user; captured photographs are saved')
                if sum(x['status']=='captured_pending_review' for x in existing.values())>=max_usable:break
                if point['id'] in existing and existing[point['id']]['status']=='captured_pending_review':continue
                url=street_url(point['lat'],point['lon'],heading=90)
                progress(f'{fsa} housing image {idx+1}/{len(points)} at DA {point["id"]}')
                record={'point':point,'url':url,'status':'needs_retry','image':None}
                try:
                    page.goto(url,wait_until='domcontentloaded',timeout=65000)
                    page.wait_for_timeout(1200 if os.environ.get('THERAPY_UNATTENDED')=='1' else 4500)
                    body=page.locator('body').inner_text(timeout=12000).lower()
                    if any(k in body for k in ('verify you are human','captcha','unusual traffic','automated queries')):
                        raise SourceUnavailable('Google requested verification; review open Firefox window')
                    if any(k in body for k in ('street view not available','no street view available','could not find street view')):
                        raise InvalidEvidence('No Street View panorama at this point')
                    image=folder/f'{point["id"]}_90.png'
                    page.screenshot(path=str(image),full_page=False)
                    if not screenshot_is_nonblank(image):
                        image.unlink(missing_ok=True);raise InvalidEvidence('Screenshot is blank or invalid')
                    record.update(status='captured_pending_review',image=str(image))
                except Exception as exc:record['error']=str(exc)
                existing[point['id']]=record
                manifest={'samples':list(existing.values()),'planned':len(points),'target':max_usable}
                write_json(folder/'manifest.json',manifest)
        finally:context.close()
    manifest={'samples':list(existing.values()),'planned':len(points),'target':max_usable}
    write_json(folder/'manifest.json',manifest)
    good=sum(x['status']=='captured_pending_review' for x in manifest['samples'])
    if good<min(minimum_usable,len(points)):
        raise InvalidEvidence(f'{fsa}: only {good} of {min(minimum_usable,len(points))} minimum usable street screenshots; individual failures saved')
    return manifest

def vision_available():
    try:
        r=requests.get('http://127.0.0.1:11434/api/tags',timeout=3)
        return any(x.get('name','').startswith('qwen2.5vl:3b') for x in r.json().get('models',[]))
    except (requests.RequestException,ValueError):return False

def classify(image_path):
    image=base64.b64encode(Path(image_path).read_bytes()).decode('ascii')
    payload={'model':MODEL,'stream':False,'format':'json','images':[image],
     'prompt':('This is a screenshot of a map/street view. Return a JSON object with: '
               'is_real_street_panorama (boolean), visible_homes (boolean), '
               'housing_types (array, any of detached, semi-detached, townhouse, '
               'low-rise apartments, mid-rise apartments, high-rise apartments, mixed housing, undeveloped, unknown), '
               'construction_visible (boolean), confidence (float 0 to 1), '
               'notes (short string). Return false if this is only map controls, a verification '
               'screen, loading screen, empty road or no houses. Never infer total residents or household income.')} 
    try:
        r=requests.post('http://127.0.0.1:11434/api/generate',json=payload,timeout=240)
        r.raise_for_status();answer=json.loads(r.json()['response'])
    except (requests.RequestException,KeyError,ValueError) as exc:
        raise SourceUnavailable(f'Local Ollama image analysis unavailable: {exc}')
    if not isinstance(answer,dict) or type(answer.get('is_real_street_panorama')) is not bool or type(answer.get('visible_homes')) is not bool:
        raise InvalidEvidence('Local vision model returned no valid visual evidence fields')
    types=answer.get('housing_types',[])
    if not isinstance(types,list) or any(t not in LABELS for t in types):
        raise InvalidEvidence('Local vision model returned unsupported housing categories')
    try:confidence=float(answer.get('confidence',0))
    except (TypeError,ValueError):confidence=0
    answer['confidence']=max(0,min(1,confidence))
    answer['validated']=bool(answer['is_real_street_panorama'] and answer['visible_homes'] and confidence>=0.85)
    return answer

def mark_review(fsa,uid,category,note):
    if category not in LABELS or len(note.strip())<8:raise InvalidEvidence('Choose a housing type and supply a meaningful observation (at least 8 characters)')
    folder=DATA/'areas'/fsa/'housing';path=folder/'manifest.json'
    report=read_json(path);samples=report.get('samples',[])
    found=next((s for s in samples if s['point']['id']==uid),None)
    if not found or found.get('status')!='captured_pending_review' or not Path(found.get('image','')).is_file():
        raise InvalidEvidence('Cannot review an image that was not captured')
    found['human_review']={'category':category,'note':note.strip()}
    if category not in RESIDENTIAL_LABELS:
        found['human_review']['qualifying_residential_evidence']=False
    else:
        found['human_review']['qualifying_residential_evidence']=True
    write_json(path,report)
    return found

def count_reviewed(evidence):
    samples=evidence.get('samples',[])
    return sum(1 for s in samples if s.get('status')=='captured_pending_review' and (
        s.get('human_review',{}).get('category') in RESIDENTIAL_LABELS or
        s.get('vision',{}).get('validated') is True))


def contextual_housing(report, lat=None, lon=None, radius_km=2.0):
    """Use only confirmed housing photographs, not screenshots that might be maps or challenges.

    If a coordinate is supplied, report evidence near that actual location.
    The labels describe photographed buildings; they never imply local population.
    """
    from .rank import haversine
    photos=[]
    for sample in report.get('samples',[]):
        if sample.get('status')!='captured_pending_review':continue
        human=sample.get('human_review') or {}
        vision=sample.get('vision') or {}
        label=human.get('category') if human.get('category') in RESIDENTIAL_LABELS else None
        if label is None and vision.get('validated'):
            label=', '.join(t for t in vision.get('housing_types',[]) if t in RESIDENTIAL_LABELS)
        if not label:continue
        point=sample.get('point') or {}
        if lat is not None:
            if 'lat' not in point or 'lon' not in point:continue
            if haversine((lat,lon),(point['lat'],point['lon']))>radius_km:continue
        photos.append({'DA':point.get('id'),'label':label,'url':sample.get('url')})
    counts={}
    for item in photos:
        for tag in item['label'].split(', '):counts[tag]=counts.get(tag,0)+1
    return {'photos':len(photos),'observed_types':dict(sorted(counts.items())),
            'samples':photos,
            'interpretation':'Housing types observed in verified street photographs, not census counts'}
