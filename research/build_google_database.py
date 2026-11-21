"""Build evidence-gated, Google-only therapy competition database and 60-area ranking.
No Psychology Today data is read anywhere in this program.
"""
from __future__ import annotations
import csv,json,math,os,sys
from collections import Counter
from pathlib import Path
from shapely.geometry import shape,Point
from shapely.ops import transform
from finder import census
from research.scan_all_maps import global_place_coordinates,distance_km
EXCLUDE_90_DAYS={'L6Z','L7A','L6X','L6R','N1T','N3S','P5N','N4W'}
COMPLETE_REASONS={'visible_end_of_list','explicit_no_results','single_place_panel'}

def repair_coordinates(row):
    """Resolve stored Google URL coordinates without making unnecessary new requests."""
    if not row.get('unlocated_links'):return row
    center=row['center']
    places={}
    for p in row.get('locations',[]):
        key=(str(p['name']).casefold(),round(p['lat'],4),round(p['lon'],4))
        places[key]=p
    unresolved=[];remote=int(row.get('outside_5km') or 0);repaired=0
    for link in row['unlocated_links']:
        point=global_place_coordinates(link['url'])
        if point is None:
            unresolved.append(link)
            continue
        repaired+=1
        if distance_km(point,center)>5:
            remote+=1
        else:
            name=link.get('name') or 'Unknown'
            key=(name.casefold(),round(point[0],4),round(point[1],4))
            places[key]={'name':name,'lat':point[0],'lon':point[1],'url':link['url']}
    row={**row,'local_count':len(places),'locations':list(places.values()),
      'unlocated_count':len(unresolved),'unlocated_links':unresolved,
      'outside_5km':remote,'coordinates_repaired_from_saved_google_urls':repaired,
      'status':'observed' if not unresolved and row.get('status') in ('observed','unresolved') else row.get('status')}
    return row

def read_sources(root):
    records={};duplicates=[]
    for p in sorted(Path(root).glob('**/results.json')):
        doc=json.loads(p.read_text())
        if 'rows' not in doc:continue
        for row in doc['rows']:
            fsa=row.get('fsa')
            if fsa in records:duplicates.append((fsa,str(p)))
            else:records[fsa]=repair_coordinates(row)
    if duplicates:raise RuntimeError('Duplicate Google FSA source evidence: '+str(duplicates[:10]))
    return records

def calculate_fsa_weighted_5km_population(codes):
    """Area-weighted 2021 FSA polygon population approximation, not a DA estimate."""
    polygons=census.fsa_geometry(print)
    populations=census.load_population('fsa',print)
    projected=[]
    for fsa,poly in polygons.items():
        if fsa not in populations:continue
        g=transform(census.project(),shape(poly))
        if not g.is_valid:g=g.buffer(0)
        if g.area<=0:continue
        projected.append((fsa,g,g.bounds,g.area,int(populations[fsa]['population'])))
    area_centers=json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())['areas']
    centers={r['fsa']:(r['lat'],r['lon']) for r in area_centers}
    results={}
    for code in codes:
        lat,lon=centers[code]
        pt=transform(census.project(),Point(lon,lat))
        circ=pt.buffer(5000,quad_segs=24)
        x1,y1,x2,y2=circ.bounds
        estimated=0.0;touch=0
        for fsa,g,bounds,area,population in projected:
            a,b,c,d=bounds
            if c<x1 or x2<a or d<y1 or y2<b:continue
            if not g.intersects(circ):continue
            overlap=g.intersection(circ).area
            if overlap:
                estimated+=population*min(1,overlap/area)
                touch+=1
        results[code]={'population_5km_estimate':round(estimated),'intersecting_fsas':touch}
    return results

def main(root='raw-google',out_dir='google-only-output'):
    out=Path(out_dir);out.mkdir(exist_ok=True,parents=True)
    full_pool=json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())['areas']
    pool={a['fsa']:a for a in full_pool}
    records=read_sources(root)
    expected=set(pool)
    observed=set(records)
    missing=sorted(expected-observed)
    extra=sorted(observed-expected)
    if extra:raise RuntimeError('Unexpected FSAs: '+str(extra[:12]))
    wrong_query=[code for code,row in records.items() if row.get('search_query')!=f'psychotherapist near {code} Ontario Canada']
    if wrong_query:raise RuntimeError('Source data used geographically unscoped Google query; replace these FSA artifacts: '+str(wrong_query[:20]))
    populations=calculate_fsa_weighted_5km_population(sorted(observed))
    rows=[];counts=Counter()
    for fsa in sorted(expected):
        a=pool[fsa];r=records.get(fsa,{})
        status=r.get('status','not_scanned')
        missing_coords=r.get('unlocated_count',None)
        links=r.get('visible_links',None)
        count=r.get('local_count',None)
        confirmed=(status=='observed' and count is not None and
            missing_coords==0 and not r.get('feed_capped',False)
            and r.get('reason') in COMPLETE_REASONS)
        reason='confirmed_observed_feed' if confirmed else (
            'no_scan' if not r else
            'capped_feed' if r.get('feed_capped') else
            'location_unresolved' if missing_coords else
            'source_incomplete' if status!='observed' else
            'list_end_unverified')
        pop=populations.get(fsa,{}).get('population_5km_estimate',0)
        ratio=round(pop/max(1,count),2) if count is not None else None
        excluded=fsa in EXCLUDE_90_DAYS
        eligible=confirmed and not excluded and pop>0
        counts[reason]+=1
        rows.append({'fsa':fsa,'population_2021_fsa':a['population_2021'],
          'population_5km_estimate':pop,'google_observed_5km':count,
          'residents_per_observed_google_listing':ratio,
          'google_visible_links':links,'unlocated_links':missing_coords,
          'outside_5km':r.get('outside_5km'),
          'feed_capped':r.get('feed_capped'),'verified':confirmed,
          'previous_90_days':excluded,'rank_eligible':eligible,
          'status':reason,'source_url':r.get('search_url',''),
          'query':'psychotherapist','latitude':a['lat'],'longitude':a['lon']})
    def rank_key(row):
        return (-row['residents_per_observed_google_listing'],
            row['google_observed_5km'] or 0,-row['population_5km_estimate'],row['fsa'])
    good=sorted((r for r in rows if r['rank_eligible']),key=rank_key)
    top=good[:60]
    with (out/'google_all_ontario_498.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    with (out/'google_top_60_candidates.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['rank']+list(rows[0]));w.writeheader()
        for i,row in enumerate(top,1):w.writerow({'rank':i,**row})
    meta={'total_populated_ontario_fsas':len(pool),'source_area_records':len(records),
          'uncollected':missing,'status_counts':dict(counts),
          'eligible_confirmed':len(good),'top60_count':len(top),
          'ranking_method':'2021 population approximated within 5 km of FSA representative point divided by max(1, unique observed Google psychotherapy query listings within the same 5km).',
          'population_assumption':'2021 population uniformly distributed inside each contributing Statistics Canada FSA polygon; approximate; not dissemination-area estimation.',
          'excluded_recent':sorted(EXCLUDE_90_DAYS),
          'note':'Google Maps feed end is an observation, not an exhaustive count of all registered clinicians; displayed source evidence retains zero and incomplete cases separately.'}
    (out/'quality_report.json').write_text(json.dumps(meta,indent=2))
    (out/'top60.json').write_text(json.dumps({'metadata':meta,'top60':top},indent=2))
    print('GOOGLE_ONLY_RESEARCH_QUALITY',json.dumps(meta),flush=True)
    print('TOP60_CANDIDATES',json.dumps([(i+1,r['fsa'],r['population_5km_estimate'],r['google_observed_5km'],r['residents_per_observed_google_listing']) for i,r in enumerate(top)]),flush=True)
    prospective=[]
    for row in rows:
        if row['previous_90_days'] or row['google_observed_5km'] is None or row['population_5km_estimate']<=0:
            continue
        if row['status'] in ('source_incomplete','no_scan','list_end_unverified'):continue
        quality=(0.2 if row['feed_capped'] else 1.0)
        if (row['unlocated_links'] or 0)>0:quality*=0.3
        score=row['residents_per_observed_google_listing']*quality
        prospective.append((score,row))
    prospective.sort(key=lambda x:(-x[0],x[1]['fsa']))
    candidates=[dict(row,first_pass_weighted_score=round(score,2)) for score,row in prospective[:180]]
    (out/'preliminary_top_180.json').write_text(json.dumps({
        'candidate_count':len(candidates),'source_fsas':len(records),
        'ranking':'Preliminary only: source quality penalties; must independently verify 5km businesses with local postal-code Google Maps queries.',
        'candidates':candidates},indent=2))
    print('PRELIMINARY_CANDIDATES',len(candidates),flush=True)
    if missing:raise RuntimeError(f'Cannot certify Ontario completeness: {len(missing)} FSAs not observed')

if __name__=='__main__':main(*(sys.argv[1:]))
