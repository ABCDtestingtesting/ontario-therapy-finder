"""Focused Google-only recheck of highest-ratio candidates against two locally scoped searches.
This script reads no Psychology Today evidence.
"""
from __future__ import annotations
import argparse,json,math,re
from pathlib import Path
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright
from finder.google_browser import scan_one,resolve_place_coordinates
from research.scan_all_maps import distance_km,global_place_coordinates

def place_key(item,coords):
    match=re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)',item['url'],re.I)
    if match:return match.group(1).lower()
    return str(item.get('name') or '').casefold().strip()+'|'+str(round(coords[0],4))+'|'+str(round(coords[1],4))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--shard',type=int,required=True)
    p.add_argument('--shards',type=int,default=20)
    p.add_argument('--input',default='research/preliminary_top_180.json')
    args=p.parse_args()
    candidates=json.loads(Path(args.input).read_text())['candidates']
    jobs=[x for i,x in enumerate(candidates) if i%args.shards==args.shard]
    output=Path('focused-output')/f'shard-{args.shard:02d}'
    output.mkdir(parents=True,exist_ok=True)
    rows=[]
    with sync_playwright() as pw:
        ctx=pw.firefox.launch_persistent_context(str(output/'profile'),headless=True,viewport={'width':1400,'height':960},locale='en-CA')
        try:
            for c in jobs:
                code=c['fsa'];center=(c['latitude'],c['longitude'])
                searches=[f'psychotherapist near {code} Ontario Canada',f'counselling therapy near {code} Ontario Canada']
                result={'fsa':code,'center':center,'source_queries':searches,'completed_queries':0,
                    'queries':[],'source_google':'Google Maps observed public search','status':'incomplete'}
                local={};unresolved={};outside={};capped=False
                for i,q in enumerate(searches):
                    try:
                        evidence=scan_one(ctx,q,*center,output/'evidence'/code/str(i),timeout_seconds=72,max_scroll=35)
                        n=len(evidence['place_links'])
                        capped=capped or n>=120
                        for item in evidence['place_links']:
                            url=item['url']
                            coords=item.get('coordinates') or global_place_coordinates(url)
                            if not coords:
                                try:coords,_=resolve_place_coordinates(ctx,url,timeout_ms=7000)
                                except Exception:pass
                            if not coords:
                                unresolved[url.split('?')[0]]=item
                                continue
                            key=place_key(item,coords)
                            if distance_km(coords,center)>5:outside[key]=item
                            else:
                                local[key]={'name':item.get('name') or 'Unknown','lat':coords[0],
                                    'lon':coords[1],'source_url':url}
                            unresolved.pop(url.split('?')[0],None)
                        result['completed_queries']+=1
                        result['queries'].append({'query':q,'visible_links':n,'completed':True,
                            'capped':n>=120,'reason':evidence['completion_reason'],'source_url':evidence['search_url']})
                    except Exception as exc:
                        result['queries'].append({'query':q,'completed':False,'error':type(exc).__name__+': '+str(exc)})
                        break
                result.update(status='verified' if len(result['queries'])==len(searches) and
                    result['completed_queries']==len(searches) and not capped and not unresolved else 'incomplete',
                    local_count=len(local),unresolved_count=len(unresolved),outside_5km=len(outside),
                    capped=capped,local_places=list(local.values()),unresolved_links=list(unresolved.values()),
                    checked_at_utc=datetime.now(timezone.utc).isoformat())
                rows.append(result)
                (output/'results.json').write_text(json.dumps({'expected':len(jobs),'completed':len(rows),
                    'shard':args.shard,'rows':rows},indent=2))
                print('FOCUSED_GOOGLE_RECHECK',json.dumps({k:v for k,v in result.items() if k not in ('local_places','unresolved_links')}),flush=True)
                if any('verification' in str(x.get('error','')).lower() or
                       '429' in str(x.get('error','')) for x in result['queries']):
                    print('Maps access restriction: stopping shard',flush=True);break
        finally:ctx.close()
    print('FOCUSED_SHARD_FINISHED',args.shard,len(rows),'of',len(jobs),flush=True)
if __name__=='__main__':main()
