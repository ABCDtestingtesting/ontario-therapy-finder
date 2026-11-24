"""Reconcile Ontario's 521 populated census FSA codes with 2021 FSA
geography and all geolocated Google business evidence, including 22 formerly
omitted Hamilton areas. Do not equate offices with individual clinicians.
"""
from __future__ import annotations
import argparse,csv,json,math,re
from collections import defaultdict
from datetime import datetime,timezone
from fractions import Fraction
from pathlib import Path
from shapely.geometry import Point,shape
from shapely import make_valid
from shapely.ops import unary_union
from shapely.strtree import STRtree
from pyproj import Transformer
import shapefile
from research.finalize_full_google_498 import clinical_title_classification
from research.external_google_clinical_adjudications import (
    independent_clinical_service_evidence,independent_nonclinical_service_evidence)

CANON=re.compile(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)',re.I)
STATUS={'clinical','nonclinical','ambiguous'}

def business_identity(place):
    url=str(place.get('source_url',''))
    if not url.startswith('https://www.google.com/maps/place/'):
        raise RuntimeError('Missing actual Google business detail provenance')
    name=str(place.get('name','')).strip()
    if not name:raise RuntimeError('Google business title missing')
    lat,lon=float(place['lat']),float(place['lon'])
    if not all(math.isfinite(v) for v in (lat,lon)) or not (41<lat<57 and -96<lon<-73):
        raise RuntimeError('Invalid Ontario Google business coordinates')
    pid=CANON.search(url)
    return ('google:'+pid.group(1).lower() if pid else
            name.casefold()+':'+str(round(lat,5))+':'+str(round(lon,5)))

def checked_class(place):
    old=place.get('observed_title_classification')
    if old is not None and old not in STATUS:
        raise RuntimeError('Unrecognized source clinical classification')
    current=clinical_title_classification(place)
    if independent_nonclinical_service_evidence(place):
        return 'nonclinical'
    if independent_clinical_service_evidence(place):
        return 'clinical'
    if old is None:return current
    if old==current:return current
    if old=='ambiguous':return current
    if current=='ambiguous':return old
    # Contradictory clinical vs nonclinical sources must be manually audited.
    return 'ambiguous'

def reconcile(areas:Path,raw:Path,plan:Path,checkpoints:Path,boundaries:Path,out:Path):
    with areas.open(newline='',encoding='utf8') as fh:
        census=list(csv.DictReader(fh))
    if len(census)!=521 or len({r['fsa'] for r in census})!=521:
        raise RuntimeError('Full Ontario 521 FSA population audit must be complete')
    by_code={r['fsa']:r for r in census}
    source=json.loads(raw.read_text())
    if source.get('source_type')!='geographically verified Google Maps place listings':
        raise RuntimeError('Original 498 FSA Google business evidence not independently verified')
    raw_places=source['all_places_by_fsa']
    if len(raw_places)!=498 or len(set(raw_places)-set(by_code))!=0:
        raise RuntimeError('Incorrect original Google FSA cohort')
    hplan=json.loads(plan.read_text())
    entries=hplan['areas']
    if (len(entries)!=22 or len({r['fsa'] for r in entries})!=22
        or any(code not in by_code for code in (r['fsa'] for r in entries))):
        raise RuntimeError('Official 22 Hamilton FSA plan invalid')
    by_hamilton={r['fsa']:r for r in entries}
    actual={}
    for path in checkpoints.glob('**/[A-Z][0-9][A-Z].json'):
        code=path.stem
        if code not in by_hamilton or code in actual:
            raise RuntimeError('Duplicate or unexpected Hamilton source checkpoint '+code)
        item=json.loads(path.read_text())
        if item.get('fsa')!=code:raise RuntimeError('Changed source FSA '+code)
        original_center=by_hamilton[code]
        center=item.get('center')
        if not center or len(center)!=2 or any(abs(float(center[i])-float(original_center[k]))>0.00001
            for i,k in enumerate(('lat','lon'))):
            raise RuntimeError('Google search source center differs from official FSA '+code)
        if len({p['key'] for p in item.get('local_places',[])})!=len(item.get('local_places',[])):
            raise RuntimeError('Duplicate recovered original Google places '+code)
        actual[code]=item
    business={}
    appearances=defaultdict(set)
    observations=0
    def add(origin,place):
        nonlocal observations
        observations+=1
        key=business_identity(place)
        lat,lon=float(place['lat']),float(place['lon'])
        typ=checked_class(place)
        appearances[key].add(origin)
        old=business.get(key)
        if old:
            if (abs(old['lat']-lat)>0.002 or abs(old['lon']-lon)>0.002):
                raise RuntimeError('Google business identity points to different geographic locations '+key)
            previous=old['observed_classification']
            if previous!=typ and previous!='ambiguous' and typ!='ambiguous':
                old['observed_classification']='ambiguous'
                old['contradictory_business_category_evidence']=True
            elif previous=='ambiguous' and typ!='ambiguous' and not old.get('contradictory_business_category_evidence'):
                old['observed_classification']=typ
            return
        business[key]={'google_identity':key,'name':place['name'],
           'lat':lat,'lon':lon,'observed_classification':typ,
           'primary_google_business_page':place['source_url'],
           'contradictory_business_category_evidence':False}
    for code,places in raw_places.items():
        for place in places:add(code,place)
    for code,item in actual.items():
        for place in item.get('local_places',[]):add(code,place)
    reader=shapefile.Reader(str(boundaries),encoding='latin1')
    fields=[f[0] for f in reader.fields[1:]]
    poly={}
    ontario=set()
    for sr in reader.iterShapeRecords():
        values=dict(zip(fields,sr.record))
        if values.get('PRUID')!='35':continue
        code=values['CFSAUID']
        if code in ontario:raise RuntimeError('Duplicated official FSA polygon '+code)
        ontario.add(code)
        g=shape(sr.shape.__geo_interface__)
        # Official 2021 polygon P0P contains fixable topological defects.
        # Repair geometry without altering its recorded census identity.
        if not g.is_valid:
            g=make_valid(g)
        if g.is_empty or g.area<=0 or not g.is_valid:
            raise RuntimeError('Invalid Statistics Canada polygon '+code)
        poly[code]=g
    if len(poly)!=520 or set(poly)!=(set(by_code)-{'M7A'}):
        raise RuntimeError('Census 2021 official polygons differ from full 521 FSA population codes')
    keys=list(poly)
    shapes=[poly[code] for code in keys]
    tree=STRtree(shapes)
    project=Transformer.from_crs(4326,3347,always_xy=True)
    counts=defaultdict(lambda:{'clinical':0,'ambiguous':0,'nonclinical':0})
    points_by_code=defaultdict(list)
    outside=[]
    for biz in business.values():
        pt=Point(*project.transform(biz['lon'],biz['lat']))
        matched=[keys[int(i)] for i in tree.query(pt) if shapes[int(i)].covers(pt)]
        if len(matched)>1:raise RuntimeError('Google business belongs to multiple FSA polygons')
        if not matched:
            outside.append(biz['google_identity'])
            continue
        code=matched[0]
        counts[code][biz['observed_classification']]+=1
        points_by_code[code].append(biz)
    # Coverage is the planned area within the union of 2021 5-km
    # reference-centre circles. It does NOT prove directory exhaustiveness.
    old_reference=json.loads(Path('research/ontario_all_populated_fsa_2021.json').read_text())
    original_centres=old_reference['areas']
    if len(original_centres)!=498 or len({x['fsa'] for x in original_centres})!=498:
        raise RuntimeError('Original 498 Ontario geographic study centre plan changed')
    original_codes={r['fsa'] for r in original_centres}
    if original_codes!=set(raw_places):
        raise RuntimeError('Original map-centre set differs from observed Google sources')
    circles=[]
    for row in original_centres+entries:
        x,y=project.transform(float(row['lon']),float(row['lat']))
        circles.append(Point(x,y).buffer(5000,quad_segs=12))
    union=unary_union(circles)
    rows=[]
    for code in sorted(by_code):
        total=int(by_code[code]['official_2021_population'])
        count=counts[code]
        frac=(poly[code].intersection(union).area/poly[code].area if code in poly else 0)
        scanned=code in raw_places or code in actual
        rows.append({
          'fsa':code,'official_2021_fsa_population':total,
          'geographically_verified_unique_clinical_businesses_lower_bound':count['clinical'],
          'geographically_verified_ambiguous_business_titles':count['ambiguous'],
          'geographically_verified_nonclinical_offices':count['nonclinical'],
          'geographically_verified_observed_businesses_per_10000_residents_lower_bound':
              round(10000*count['clinical']/total,9),
          'all_ambiguous_offices_count_as_therapists_scenario_per_10000':
              round(10000*(count['clinical']+count['ambiguous'])/total,9),
          'fraction_of_FSA_geography_within_planned_5km_collection_circles':round(min(1,frac),9),
          'Google_original_FSA_search_source_present':scanned,
          'Hamilton_new_2026_Google_attempted':code in actual,
          '2021_Google_full_FSA_search_exhaustiveness_verified':False,
          'individual_registered_clinician_count':None,
          'Google_zero_businesses_proves_no_therapists':False,
          'previously_researched_last_90_days_excluded_from_ranking':False,
          'FSA_has_official_2021_geographic_polygon':code in poly,
          'source_complete_for_ranking':False,
        })
    if len(rows)!=521:raise RuntimeError('Entire Ontario 521 population FSA audit truncated')
    key=lambda r:(Fraction(r['geographically_verified_unique_clinical_businesses_lower_bound'],
                           r['official_2021_fsa_population']),
                  -r['official_2021_fsa_population'],r['fsa'])
    ranked=sorted(rows,key=key)
    screened=[r for r in ranked if
        r['fraction_of_FSA_geography_within_planned_5km_collection_circles']>=0.90
        and r['official_2021_fsa_population']>=10000]
    if len(screened)<60:raise RuntimeError('Insufficient partial geographical evidence for provisional 60')
    out.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0])
    def save(name,data,rank=False):
        with (out/name).open('w',newline='',encoding='utf8') as fh:
            w=csv.DictWriter(fh,fieldnames=(['provisional_rank'] if rank else [])+fields)
            w.writeheader()
            for i,row in enumerate(data,1):
                w.writerow({'provisional_rank':i,**row} if rank else row)
    save('Ontario_521_Geographically_Deduplicated_Google_Office_Audit.csv',rows)
    save('Ontario_60_Partial_Google_Office_Observations_NOT_CERTIFIED.csv',ranked[:60],True)
    save('Ontario_60_Geographically_Screened_Google_Office_Leads_NOT_CERTIFIED.csv',screened[:60],True)
    (out/'Ontario_521_Google_Business_Geographic_Identifiers.json').write_text(
        json.dumps({'source':'2021 FSA polygons','businesses_by_official_fsa':dict(points_by_code)},indent=2))
    report={
      'Ontario_2021_nonzero_population_fsa_codes':521,
      'Ontario_2021_official_fsa_polygons':520,
      'FSA_codes_originally_scanned':498,
      'Hamilton_2026_new_scan_checkpoints':len(actual),
      'Hamilton_FSA_codes_still_without_new_scans':sorted(set(by_hamilton)-set(actual)),
      'special_M7A_population_without_polygon':5,
      'original_plus_new_business_observations':observations,
      'uniquely_identified_Google_businesses':len(business),
      'unique_offices_inside_2021_ontario_geography':sum(sum(x.values()) for x in counts.values()),
      'businesses_outside_official_ontario_polygons':len(outside),
      'confirmed_explicit_clinical_offices_geographically_assigned':sum(x['clinical'] for x in counts.values()),
      'ambiguous_google_businesses_geographically_assigned':sum(x['ambiguous'] for x in counts.values()),
      'FSA_codes_planned_5km_circle_coverage_ge90percent':sum(
          r['fraction_of_FSA_geography_within_planned_5km_collection_circles']>=.90 for r in rows),
      'provisional_10k_population_geographically_screened_candidates':len(screened),
      'source_model_certified_exact_lowest_60':False,
      'individual_therapists_counted':False,
      'Google_search_exhaustive':False,
      'source_collection_UTC':datetime.now(timezone.utc).isoformat()
    }
    (out/'Ontario_521_Location_Crosscheck_Report.json').write_text(json.dumps(report,indent=2))
    print('ONTARIO_521_CLINICAL_GOOGLE_GEO_SOURCE_CROSSAUDIT',json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('areas','raw','plan','checkpoints','boundaries','out'):
        p.add_argument('--'+key,required=True,type=Path)
    a=p.parse_args()
    reconcile(a.areas,a.raw,a.plan,a.checkpoints,a.boundaries,a.out)
