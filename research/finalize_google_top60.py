"""Assemble 60 fully geolocated Google-only Ontario opportunity candidates.
Requires the independent two-query confirmation for each recommended FSA.
"""
import csv,json,math,sys,re
from pathlib import Path
from collections import Counter

HISTORY_90_DAYS={'L6Z','L7A','L6X','N1T','N3S','P5N','N4W'}

def load_focused(root):
    data={};dup=[]
    for p in Path(root).glob('**/results.json'):
        doc=json.loads(p.read_text())
        if 'rows' not in doc:continue
        for row in doc['rows']:
            code=row['fsa']
            if code in data:dup.append(code)
            else:data[code]=row
    if dup:raise RuntimeError('Duplicate second-pass Google data: '+str(dup[:10]))
    return data

def place_key(p):
    url=p.get('source_url') or p.get('url','')
    m=re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)',url,re.I)
    if m:return m.group(1).casefold()
    name=str(p.get('name') or p.get('title') or '').casefold().strip()
    return name+'|'+str(round(p['lat'],4))+'|'+str(round(p['lon'],4))

def main(focused_root='focused-output-raw',outdir='google-60-final'):
    out=Path(outdir);out.mkdir(exist_ok=True,parents=True)
    screening=json.loads(Path('research/preliminary_top_180.json').read_text())
    candidates=screening['candidates']
    focused=load_focused(focused_root)
    result=[];discarded=Counter();details=[]
    for candidate in candidates:
        code=candidate['fsa'];follow=focused.get(code)
        if code in HISTORY_90_DAYS:
            discarded['recently_returned']+=1;continue
        if not follow:
            discarded['missing_second_pass']+=1
            details.append({'fsa':code,'issue':'missing_second_pass'});continue
        if follow['status']!='verified' or follow['unresolved_count']!=0 or follow['capped']:
            discarded['unverified_second_pass']+=1
            details.append({'fsa':code,'issue':'unverified_second_pass','google_status':follow['status'],
                            'missing_coordinates':follow['unresolved_count'],'capped':follow['capped'],
                            'queries':follow['queries']});continue
        if follow['completed_queries']<2:
            discarded['incomplete_two_queries']+=1;continue
        if candidate['population_5km_estimate']<=0:
            discarded['zero_estimated_population']+=1;continue
        unique={}
        for p in follow['local_places']:
            unique[place_key(p)]=p
        providers=list(unique.values())
        competition=len(providers)
        pop=int(candidate['population_5km_estimate'])
        ratio=round(pop/max(1,competition),1)
        result.append({
          'fsa':code,'population_5km_estimate_2021':pop,'google_therapy_listings_5km':competition,
          'residents_per_google_listing':ratio,'population_2021_fsa':candidate['population_2021_fsa'],
          'latitude':candidate['latitude'],'longitude':candidate['longitude'],
          'google_queries_completed':follow['completed_queries'],
          'google_location_unresolved':follow['unresolved_count'],
          'google_search_links':'; '.join(q['source_url'] for q in follow['queries'] if q.get('source_url')),
          'provider_names':'; '.join(p['name'] for p in providers[:25]),
          'verified_at_utc':follow['checked_at_utc'],'provider_details':providers})
    result.sort(key=lambda r:(-r['residents_per_google_listing'],r['google_therapy_listings_5km'],
                             -r['population_5km_estimate_2021'],r['fsa']))
    selected=result[:60]
    hdr=['rank','fsa','population_5km_estimate_2021','google_therapy_listings_5km',
      'residents_per_google_listing','population_2021_fsa','latitude','longitude',
      'google_queries_completed','google_location_unresolved','google_search_links',
      'provider_names','verified_at_utc']
    with (out/'Ontario_Google_60_verified.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=hdr);w.writeheader()
        for i,r in enumerate(selected,1):w.writerow({'rank':i,**{k:r.get(k) for k in hdr if k!='rank'}})
    with (out/'Ontario_Google_60_verified.json').open('w') as f:
        json.dump({'metric':'Estimated 2021 population within five kilometres / max(1, unique public Google Maps location listings found via 2 postal-area-specific searches)',
                   'source':'Official Statistics Canada 2021 FSA boundaries and populations, live Google Maps browser results',
                   'population_caveat':'Approximates uniform population within FSA polygons; local dissemination-area estimates would improve rural accuracy',
                   'result_count':len(selected),
                   'excluded_last_90_days':sorted(HISTORY_90_DAYS),
                   'results':[{'rank':i,**r} for i,r in enumerate(selected,1)]},f,indent=2)
    quality={'input_candidates':len(candidates),'second_pass_records':len(focused),
             'google_verified_candidates':len(result),'selected':len(selected),
             'reasons_excluded':dict(discarded),'unverified_details':details,
             'return_safe':len(selected)==60,
             'no_psychology_today_used':True}
    (out/'Google_Research_Quality.json').write_text(json.dumps(quality,indent=2))
    print('GOOGLE_60_FINAL_VALIDATION',json.dumps({k:v for k,v in quality.items() if k!='unverified_details'}),flush=True)
    print('GOOGLE_60_FINAL_POSTAL_CODES',[r['fsa'] for r in selected],flush=True)
    if len(selected)!=60:raise RuntimeError(f'Cannot confirm 60 resolved Google-only areas: only {len(selected)} verified')
if __name__=='__main__':main(*sys.argv[1:])
