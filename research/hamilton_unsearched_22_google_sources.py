"""Fill 22 previously omitted Hamilton 2021 FSA geography with genuinely
localized Google source scans, using free official StatsCan boundaries.
M7A has population five but no official 2021 FSA polygon and stays separate.
"""
from __future__ import annotations
import argparse,csv,json,math,time
from pathlib import Path
from datetime import datetime,timezone
import shapefile
from shapely.geometry import Point,shape
from pyproj import Transformer
from playwright.sync_api import sync_playwright
from research.recover_google_tiles import run_area
from research.google_measured_recenter_runner import refresh
from finder import google_browser

EXPECTED='L0R L8B L8E L8G L8H L8J L8K L8L L8M L8N L8P L8R L8S L8T L8V L8W L9A L9B L9C L9G L9H L9K'.split()
POP_FIELD='Population and dwelling counts (3):Population, 2021[1]'

def plan(boundaries:Path,census:Path,out:Path):
    code_set=set(EXPECTED)
    pop={}
    with census.open(newline='',encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            if row['GEO'] in code_set:
                if row['GEO'] in pop or row['DGUID']!='2021A0011'+row['GEO']:
                    raise RuntimeError('Missing unique official Hamilton population '+row['GEO'])
                pop[row['GEO']]=int(row[POP_FIELD])
    if set(pop)!=code_set or any(n<=0 for n in pop.values()):
        raise RuntimeError('Official 22 Hamilton FSA population values missing')
    coords=Transformer.from_crs(3347,4326,always_xy=True)
    reader=shapefile.Reader(str(boundaries),encoding='latin1')
    fields=[x[0] for x in reader.fields[1:]]
    records={}
    n=0
    for sr in reader.iterShapeRecords():
        data=dict(zip(fields,sr.record))
        if data.get('PRUID')!='35':continue
        n+=1
        code=data['CFSAUID']
        if code not in code_set:continue
        g=shape(sr.shape.__geo_interface__)
        if code in records or not g.is_valid or g.is_empty:
            raise RuntimeError('Invalid or duplicate 2021 Hamilton FSA geometry '+code)
        central=g.representative_point()
        lon,lat=coords.transform(central.x,central.y)
        if not (42.0<lat<45.0 and -81.0<lon<-78.0 and g.covers(central)):
            raise RuntimeError('Invalid Ontario Hamilton FSA population search centre '+code)
        footprint=min(1.0,max(0.0,g.intersection(central.buffer(5000,quad_segs=24)).area/g.area))
        records[code]={'fsa':code,'lat':round(lat,7),'lon':round(lon,7),
            'population_2021':pop[code],
            '2021_fsa_polygon_area_sqkm':round(g.area/1000000,5),
            'single_five_km_catchment_polygon_area_share':round(footprint,7),
            'Google_search_had_prior_source':False,
            'point_from_2021_official_fsa_polygon':True}
    if n!=520 or len(records)!=22:
        raise RuntimeError('Expected 520 provincewide official 2021 FSA polygons including 22 Hamilton FSAs')
    d={'source':'Statistics Canada 2021 FSA polygons and population',
       'Ontario_all_geographic_fsas':520,'Hamilton_unsearched':22,
       'excluded_from_Google_scarcity_verification':True,
       'areas':[records[k] for k in EXPECTED]}
    out.mkdir(parents=True,exist_ok=True)
    (out/'hamilton_22_verified_centres.json').write_text(json.dumps(d,indent=2))
    print('HAMILTON_22_OFFICIAL_CENSUS_SOURCE_PLAN',json.dumps({'fsas':EXPECTED,
        'small_fsa_5km_coverage':{k:r['single_five_km_catchment_polygon_area_share'] for k,r in records.items()}}),flush=True)
    return d

def scan(source:Path,index:int,out:Path,seconds:int):
    d=json.loads(source.read_text())
    if len(d['areas'])!=22 or not 0<=index<22 or not 90<=seconds<=900:
        raise RuntimeError('Unverified 22-FSA source plan or time budget')
    area=d['areas'][index]
    code=area['fsa']
    root=out/'checkpoints'
    root.mkdir(parents=True,exist_ok=True)
    google_browser._refresh_map_area_results=refresh
    with sync_playwright() as pw:
        browser=pw.firefox.launch_persistent_context(
            str(out/'source-firefox-profile'),headless=True,
            viewport={'width':1400,'height':960},locale='en-CA')
        try:
            result=run_area(browser,dict(area,ranking_cutoff=0.00000001,
                      population_5km_estimate=int(area['population_2021']),
                      baseline_observed_5km=0),root,seconds)
        finally:
            browser.close()
    summary={'fsa':code,'status':result.get('status'),
      'all_18_google_tiles_searched':result.get('completed_coverage_tiles')==18,
      'remaining_tile_queries':len(result.get('pending',[])),
      'capped_google_feed_count':result.get('capped_leaf_tiles'),
      'unique_locally_observed_google_offices':result.get('unique_observed_local_places'),
      'original_fsa_polygon_area_covered_by_one_center_circle':
          area['single_five_km_catchment_polygon_area_share'],
      'entire_FSA_geography_searched':False,
      'population_denominator':area['population_2021'],
      'absence_of_therapists_verified':False,
      'checked_utc':datetime.now(timezone.utc).isoformat()}
    (out/'source-result.json').write_text(json.dumps(summary,indent=2))
    print('HAMILTON_PREVIOUSLY_UNSEARCHED_FSA_RESULT',json.dumps(summary),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['plan','scan'])
    p.add_argument('--boundaries',type=Path)
    p.add_argument('--census',type=Path)
    p.add_argument('--source',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--index',type=int)
    p.add_argument('--seconds',type=int,default=360)
    a=p.parse_args()
    if a.action=='plan':
        if not a.boundaries or not a.census:raise RuntimeError('Official geography source missing')
        plan(a.boundaries,a.census,a.out)
    else:
        if a.index is None or not a.source:raise RuntimeError('Missing verified source code selection')
        scan(a.source,a.index,a.out,a.seconds)
