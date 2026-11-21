"""One-pass observed Google Maps therapist competition for every official Ontario FSA.
Runs sharded on hosted macOS; refuses to equate missing coordinates with zero.
"""
import argparse,csv,json,math,os,time,traceback,re
from urllib.parse import unquote
from pathlib import Path
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright
from finder.google_browser import scan_one
from finder.common import HumanVerificationRequired,SourceUnavailable

def distance_km(a,b):
    r=math.pi/180
    x=math.sin((b[0]-a[0])*r/2)**2+math.cos(a[0]*r)*math.cos(b[0]*r)*math.sin((b[1]-a[1])*r/2)**2
    return 12742*math.asin(min(1,math.sqrt(x)))

def global_place_coordinates(url):
    """Coordinates in a Google place's identity URL can be anywhere in the world."""
    url=unquote(url)
    m=list(re.finditer(r'!3d(-?\\d+(?:\\.\\d+)?)!4d(-?\\d+(?:\\.\\d+)?)',url))
    if m:
        lat,lon=map(float,m[-1].groups())
        if -90<=lat<=90 and -180<=lon<=180:return (lat,lon)
    m=list(re.finditer(r'!2d(-?\\d+(?:\\.\\d+)?)!3d(-?\\d+(?:\\.\\d+)?)',url))
    if m:
        lon,lat=map(float,m[-1].groups())
        if -90<=lat<=90 and -180<=lon<=180:return (lat,lon)
    return None

def score_links(links,center):
    known={};missing={};outside=0
    for x in links:
        url=x.get('url','')
        coords=x.get('coordinates') or global_place_coordinates(url)
        if coords is None:
            missing[url.split('?')[0]]=x
            continue
        if distance_km(coords,center)>5:
            outside+=1
            continue
        name=str(x.get('name') or url).strip()
        key=name.casefold()+'|'+str(round(coords[0],4))+'|'+str(round(coords[1],4))
        known[key]={'name':name,'lat':coords[0],'lon':coords[1],'url':url}
    return known,missing,outside

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--shard',type=int,required=True)
    parser.add_argument('--shards',type=int,default=20)
    args=parser.parse_args()
    areas=json.loads(Path('research/ontario_401_fsa_2021.json').read_text())['areas']
    areas=[x for i,x in enumerate(areas) if i%args.shards==args.shard]
    folder=Path('scan-output')/f'shard-{args.shard:02d}'
    folder.mkdir(exist_ok=True,parents=True)
    rows=[]
    def save():
        (folder/'results.json').write_text(json.dumps({
            'shard':args.shard,'shards':args.shards,'items_expected':len(areas),
            'items_completed':len(rows),'collected_at_utc':datetime.now(timezone.utc).isoformat(),
            'rows':rows},indent=2))
    with sync_playwright() as pw:
        ctx=pw.firefox.launch_persistent_context(str(folder/'firefox_profile'),headless=True,
                viewport={'width':1400,'height':960},locale='en-CA')
        try:
            for a in areas:
                center=(a['lat'],a['lon']);code=a['fsa']
                record={'fsa':code,'center':center,'population_2021':a['population_2021'],
                        'status':'not_checked'}
                try:
                    evidence=scan_one(ctx,'psychotherapist',*center,
                        folder/'evidence'/code,timeout_seconds=65,max_scroll=30)
                    known,unknown,outside=score_links(evidence['place_links'],center)
                    c=len(evidence['place_links'])
                    record.update(status='observed' if not unknown else 'unresolved',local_count=len(known),
                        unlocated_count=len(unknown),outside_5km=outside,
                        unlocated_links=list(unknown.values()),
                        visible_links=c,feed_capped=c>=120,locations=list(known.values()),
                        search_url=evidence['search_url'],reason=evidence['completion_reason'])
                except HumanVerificationRequired as exc:
                    record.update(status='blocked',error=str(exc))
                except Exception as exc:
                    record.update(status='incomplete',error=f'{type(exc).__name__}: {exc}')
                rows.append(record);save()
                print('FSA_OBSERVATION',json.dumps({k:v for k,v in record.items() if k!='locations'}),flush=True)
                if record['status']=='blocked':
                    print('Stopping shard on provider access restriction; remainder not assessed',flush=True)
                    break
        finally:
            ctx.close()
    print('SHARD_FINISHED',args.shard,len(rows),'of',len(areas),flush=True)
    save()

if __name__=='__main__':main()
