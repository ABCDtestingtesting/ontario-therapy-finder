"""Provisional source-audited Google clinic density within official Ontario FSA
polygons using complete 2021 Statistics Canada FSA population denominators.

Each Google office has one deduplicated geolocation. Google counts represent
observed businesses, not a census of licensed therapists. Missing businesses,
ambiguous titles and FSA geographic coverage remain explicit.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
import shapefile
from pyproj import Transformer
from shapely.geometry import Point,shape
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely import make_valid

POPULATION_FIELD = 'Population and dwelling counts (3):Population, 2021[1]'
EXPECTED_ON_FSAS=520
EXPECTED_EXCLUDED_HAMILTON=22
EXPECTED_STUDY_FSAS=498

def evaluate(boundaries:Path,census:Path,centres:Path,observed:Path,out:Path):
    area_doc=json.loads(centres.read_text())
    areas=area_doc['areas']
    allowed={x['fsa']:x for x in areas}
    if (area_doc.get('excludes')!='Hamilton municipal FSA list'
        or len(areas)!=EXPECTED_STUDY_FSAS or len(allowed)!=EXPECTED_STUDY_FSAS):
        raise RuntimeError('498 distinct Ontario FSA sources outside Hamilton required')
    populations={}
    with census.open(newline='',encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            code=row['GEO']
            if code not in allowed:continue
            if code in populations or row['DGUID']!='2021A0011'+code:
                raise RuntimeError('Duplicate/invalid Statistics Canada FSA code '+code)
            amount=int(row[POPULATION_FIELD])
            if amount<=0 or amount!=int(allowed[code]['population_2021']):
                raise RuntimeError('Population mismatch against official 2021 FSA '+code)
            populations[code]=amount
    if set(populations)!=set(allowed):
        raise RuntimeError('Missing official Statistics Canada FSA population records')
    reader=shapefile.Reader(str(boundaries),encoding='latin1')
    fields=[f[0] for f in reader.fields[1:]]
    geometry={}
    provincial=set()
    for sr in reader.iterShapeRecords():
        info=dict(zip(fields,sr.record))
        if info['PRUID']!='35':continue
        code=info['CFSAUID']
        provincial.add(code)
        if code not in allowed:continue
        g=shape(sr.shape.__geo_interface__)
        if not g.is_valid:g=make_valid(g)
        if g.is_empty or g.area<=0 or code in geometry:
            raise RuntimeError('Invalid/duplicate StatsCan FSA polygon '+code)
        geometry[code]=g
    if (len(provincial)!=EXPECTED_ON_FSAS
        or len(provincial-set(allowed))!=EXPECTED_EXCLUDED_HAMILTON
        or set(geometry)!=set(allowed)):
        raise RuntimeError('Provincewide official FSA boundaries differ from Hamilton-excluded study')
    original=json.loads(observed.read_text())
    if original.get('source_type')!='geographically verified Google Maps place listings':
        raise RuntimeError('Unsupported original Google business provenance')
    source=original['all_places_by_fsa']
    if set(source)!=set(allowed):
        raise RuntimeError('Original Google source missing an eligible FSA')
    sites={}
    total_observations=0
    for fsa,places in source.items():
        for business in places:
            total_observations+=1
            key=business['key']
            if key in sites:
                old=sites[key]
                if (old['name']!=business['name']
                    or abs(float(old['lat'])-float(business['lat']))>0.00001
                    or abs(float(old['lon'])-float(business['lon']))>0.00001
                    or old['observed_title_classification']!=business['observed_title_classification']):
                    raise RuntimeError('Conflicting real Google place ID '+key)
                continue
            if (business['observed_title_classification'] not in ('clinical','ambiguous','nonclinical')
                or not str(business.get('name','')).strip()
                or not str(business.get('source_url','')).startswith('https://www.google.com/maps/place/')):
                raise RuntimeError('Invalid source location '+fsa)
            lat,lon=float(business['lat']),float(business['lon'])
            if not (-90<=lat<=90 and -180<=lon<=180):
                raise RuntimeError('Invalid Google place coordinates '+key)
            sites[key]=business
    project=Transformer.from_crs(4326,3347,always_xy=True)
    codes=list(geometry)
    polys=[geometry[code] for code in codes]
    tree=STRtree(polys)
    counts=defaultdict(lambda:{'clinical':0,'nonclinical':0,'ambiguous':0})
    outside=0
    for business in sites.values():
        pt=Point(*project.transform(float(business['lon']),float(business['lat'])))
        hits=[codes[int(i)] for i in tree.query(pt) if polys[int(i)].covers(pt)]
        if len(hits)>1:raise RuntimeError('Google office intersects multiple census postal boundaries')
        if not hits:
            outside+=1
            continue
        counts[hits[0]][business['observed_title_classification']]+=1
    circles=[Point(*project.transform(float(x['lon']),float(x['lat']))).buffer(5000,quad_segs=8)
             for x in areas]
    cover=unary_union(circles)
    rows=[]
    for code,g in geometry.items():
        count=counts[code]
        coverage=max(0.0,min(1.0,g.intersection(cover).area/g.area))
        pop=populations[code]
        rows.append({
            'fsa':code,'official_2021_fsa_population':pop,
            'observed_unique_title_confirmed_clinical_businesses':count['clinical'],
            'observed_unique_ambiguous_business_titles':count['ambiguous'],
            'observed_unique_nonclinical_businesses':count['nonclinical'],
            'clinical_business_lower_bound_per_10000':round(count['clinical']*10000/pop,9),
            'all_ambiguous_clinical_scenario_per_10000':round((count['clinical']+count['ambiguous'])*10000/pop,9),
            'share_of_official_fsa_geography_inside_original_5km_collection_discs':round(coverage,9),
            'absence_of_unlisted_therapists_verified':False,
            'all_office_practitioners_individually_counted':False,
            'source_observation_model_certified':False,
        })
    if len(rows)!=498:raise RuntimeError('Bad FSA output cardinality')
    out.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0])
    def write(name,items,numbered=False):
        with (out/name).open('w',newline='',encoding='utf8') as fh:
            w=csv.DictWriter(fh,fieldnames=(['provisional_rank'] if numbered else [])+fields)
            w.writeheader()
            for index,item in enumerate(items,1):
                w.writerow({'provisional_rank':index,**item} if numbered else item)
    write('Ontario_498_Official_FSA_Population_Google_Business_Audit.csv',sorted(rows,key=lambda x:x['fsa']))
    lower=sorted(rows,key=lambda x:(x['clinical_business_lower_bound_per_10000'],
                                    -x['official_2021_fsa_population'],x['fsa']))
    write('Ontario_60_Observed_Clinical_Lower_Bounds_NOT_CERTIFIED.csv',lower[:60],True)
    safer=sorted((x for x in rows if
        x['share_of_official_fsa_geography_inside_original_5km_collection_discs']>=0.9),
        key=lambda x:(x['all_ambiguous_clinical_scenario_per_10000'],
                      -x['official_2021_fsa_population'],x['fsa']))
    if len(safer)<60:raise RuntimeError('Fewer than 60 areas have reasonable search footprint coverage')
    write('Ontario_60_Geographically_Screened_Observed_Place_Candidates_NOT_CERTIFIED.csv',safer[:60],True)
    report={
      'ontario_official_2021_fsa_polygons':len(provincial),
      'eligible_ontario_fsas_outside_hamilton':len(rows),
      'excluded_hamilton_fsa_codes':sorted(provincial-set(allowed)),
      'eligible_official_2021_fsa_population':sum(populations.values()),
      'google_original_geolocated_fsa_observations':total_observations,
      'google_original_unique_businesses':len(sites),
      'unique_google_businesses_mapped_to_eligible_fsa':sum(sum(v.values()) for v in counts.values()),
      'businesses_outside_study_fsa_boundaries':outside,
      'unique_google_title_clinical_businesses':sum(v['clinical'] for v in counts.values()),
      'unique_ambiguous_google_businesses':sum(v['ambiguous'] for v in counts.values()),
      'fsas_with_at_least_90_percent_geographic_footprint':len(safer),
      'fsas_with_less_than_90_percent_geographic_footprint':len(rows)-len(safer),
      'absence_of_therapists_inferred_from_empty_google':False,
      'certified_60_lowest_registered_therapist_to_population_fsas':False,
      'limitations':'Observed businesses, not practitioner headcounts; source only collected within nearby 5km areas, Google directories are incomplete, ambiguous place titles remain unresolved.'
    }
    (out/'Ontario_Official_FSA_Place_Coverage_Report.json').write_text(json.dumps(report,indent=2))
    print('OFFICIAL_ON_498_FSA_BOUNDARIES_AND_BUSINESSES',json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for item in ('boundaries','census','centres','observed','out'):
        p.add_argument('--'+item,required=True,type=Path)
    a=p.parse_args()
    evaluate(a.boundaries,a.census,a.centres,a.observed,a.out)
