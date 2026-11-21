"""Pilot local-intent Google Maps queries with globally valid link-coordinate parsing."""
from pathlib import Path
import json,re,math,time
from playwright.sync_api import sync_playwright
from finder.google_browser import scan_one
def coords(url):
    pairs=list(re.finditer(r'!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)',url))
    if pairs:
        lat,lon=map(float,pairs[-1].groups())
        if -90<=lat<=90 and -180<=lon<=180:return lat,lon
    pairs=list(re.finditer(r'!2d(-?\d+(?:\.\d+)?)!3d(-?\d+(?:\.\d+)?)',url))
    if pairs:
        lon,lat=map(float,pairs[-1].groups())
        if -90<=lat<=90 and -180<=lon<=180:return lat,lon
    return None
def km(a,b):
    p=math.pi/180;v=math.sin((a[0]-b[0])*p/2)**2+math.cos(a[0]*p)*math.cos(b[0]*p)*math.sin((a[1]-b[1])*p/2)**2
    return 12742*math.asin(min(1,v**0.5))
if __name__=='__main__':
    data=json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())
    pool={x['fsa']:x for x in data['areas']}
    targets=['N4W','P9N','K0A','N1T','P2A']
    out=Path('pilot-query-results');out.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        ctx=pw.firefox.launch_persistent_context(str(out/'profile'),headless=True,viewport={'width':1400,'height':960},locale='en-CA')
        for code in targets:
            a=pool[code];center=(a['lat'],a['lon'])
            for query in ('psychotherapist',f'psychotherapist near {code} Ontario Canada'):
                try:
                    e=scan_one(ctx,query,*center,out/f'{code}-{len(query)}',timeout_seconds=65,max_scroll=30)
                    resolved={};outside=0;unresolved=[]
                    for link in e['place_links']:
                        xy=link['coordinates'] or coords(link['url'])
                        if not xy:unresolved.append(link);continue
                        if km(xy,center)>5:outside+=1;continue
                        key=(link['name'].lower(),round(xy[0],4),round(xy[1],4))
                        resolved[key]=link['url']
                    row={'code':code,'query':query,'status':'observed','places':len(e['place_links']),'local_count':len(resolved),'outside':outside,'unresolved':len(unresolved),'completion':e['completion_reason'],'sample':list(resolved)[:7]}
                except Exception as exc:row={'code':code,'query':query,'status':'error','reason':str(exc)}
                print('QUERY_TRIAL',json.dumps(row,default=str),flush=True)
                with (out/'observations.jsonl').open('a') as f:f.write(json.dumps(row,default=str)+'\n')
        ctx.close()
