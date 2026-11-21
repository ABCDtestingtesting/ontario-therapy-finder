"""Street-level geographic opportunity screening; strict provenance and completion gate."""
from __future__ import annotations
import csv,math
from pathlib import Path
from .common import DATA,OUTPUT,InvalidEvidence,write_json,read_json
from . import state,census,housing

def haversine(p,q):
    x1,y1=map(math.radians,p);x2,y2=map(math.radians,q)
    a=math.sin((x2-x1)/2)**2+math.cos(x1)*math.cos(x2)*math.sin((y2-y1)/2)**2
    return 12742.0176*math.asin(min(1,math.sqrt(a)))

def nearby(locations,lat,lon,radius_km=5):
    found={}
    for loc in locations:
        if 'lat' not in loc or 'lon' not in loc:raise InvalidEvidence('Google listing without coordinates entered comparison')
        if haversine((lat,lon),(loc['lat'],loc['lon']))<=radius_km:
            found[loc['id']]=loc
    return list(found.values())

def merged_locations(fsas):
    all_places={}
    for code in fsas:
        path=DATA/'areas'/code/'google'/'locations.json'
        if not path.is_file():raise InvalidEvidence(f'No Google locations evidence for {code}')
        for p in read_json(path)['locations']:
            # Site IDs may differ between search passes; CID/place_id takes precedence.
            all_places[p['id']]=p
    return list(all_places.values())

def analyse(fsas,min_sites_each=4,max_sites_each=70):
    if len(set(fsas)) < 2:
        raise InvalidEvidence('At least two distinct postal areas are needed for two recommendations')
    if len(set(fsas)) != len(fsas):
        raise InvalidEvidence('Duplicate postal area selections are not valid for this comparison')
    state.require_complete(fsas)
    all_google=merged_locations(fsas)
    fsas_geometry=census.fsa_geometry();da_pop=census.load_population('da')
    fsa_population=census.load_population('fsa')
    rows=[];sites=[]
    snapshot=state.read()
    for code in fsas:
        if code not in fsas_geometry:raise InvalidEvidence(f'FSA boundary missing: {code}')
        g=fsas_geometry[code]
        da_geos=census.da_near(code,g)
        point=census.representative(g)
        pop=census.catchment(*point,da_geos,da_pop,radius_km=5)
        maps=nearby(all_google,*point)
        if not maps:raise InvalidEvidence(f'{code} has zero mapped clinics in representative 5 km circle; extra source audit required')
        pt=snapshot['areas'][code]['psychology_today']['evidence']
        hou=snapshot['areas'][code]['housing']['evidence']
        evidence_housing=housing.contextual_housing(hou)
        if code not in fsa_population or fsa_population[code]['population']<=0:
            raise InvalidEvidence(f'Cannot compare PT competition for {code}: missing official FSA population')
        fsa_people=fsa_population[code]['population']
        google_rate=10000*len(maps)/pop['population_2021_estimate']
        pt_rate=10000*pt['classes']['local_postal_listing']/fsa_people
        combined=(google_rate+pt_rate)/2
        row={'fsa':code,'population_5km_2021_est':pop['population_2021_estimate'],
             'occupied_dwellings_5km_2021_est':pop['occupied_dwellings_2021_estimate'],
             'google_locations_5km':len(maps),
             'google_locations_per_10k_residents':round(google_rate,2),
             'population_per_mapped_location':round(pop['population_2021_estimate']/len(maps)),
             'pt_postal_listings_fsa':pt['classes']['local_postal_listing'],
             'pt_local_profiles_per_10k_fsa_residents':round(pt_rate,2),
             'combined_competition_indicator':round(combined,3),
             'pt_online_only':pt['classes']['online_only'],
             'pt_serves_area':pt['classes']['serves_area'],
             'pt_unique_profiles':pt['unique_profiles'],
             'housing_photos_reviewed':housing.count_reviewed(hou),
             'observed_housing_types':'; '.join(f'{k}:{v}' for k,v in evidence_housing['observed_types'].items()),
             'census_year':2021}
        rows.append(row)
        candidates=housing.sample_points(g,da_geos,da_pop,limit=max_sites_each,min_gap=400)
        if len(candidates)<min_sites_each:raise InvalidEvidence(f'{code} has too few populated candidate locations ({len(candidates)})')
        for p in candidates:
            localpop=census.catchment(p['lat'],p['lon'],da_geos,da_pop,5)
            nearby_google=nearby(all_google,p['lat'],p['lon'],5)
            n=len(nearby_google)
            housing_near=housing.contextual_housing(hou,p['lat'],p['lon'],radius_km=2.0)
            local_google_rate=10000*n/localpop['population_2021_estimate']
            local_combined=(local_google_rate+pt_rate)/2
            sites.append({'fsa':code,'census_DA':p['id'],'latitude':p['lat'],'longitude':p['lon'],
                          'population_5km_2021_est':localpop['population_2021_estimate'],
                          'dwellings_5km_2021_est':localpop['occupied_dwellings_2021_estimate'],
                          'mapped_locations_5km':n,'population_per_location':round(localpop['population_2021_estimate']/n) if n else None,
                          'google_locations_per_10k_residents':round(local_google_rate,2),
                          'pt_local_profiles_per_10k_fsa_residents':round(pt_rate,2),
                          'combined_competition_indicator':round(local_combined,3),
                          'housing_photos_within_2km':housing_near['photos'],
                          'observed_housing_nearby':'; '.join(housing_near['observed_types']),
                          'status':('screened' if housing_near['photos'] else 'housing_photo_gap') if n else 'zero_competitors_reaudit',
                          'google_maps_url':f'https://www.google.com/maps/search/?api=1&query={p["lat"]}%2C{p["lon"]}'})
    rows.sort(key=lambda r:(r['combined_competition_indicator'],-r['population_5km_2021_est']))
    sites.sort(key=lambda r:(r['status']!='screened',r['combined_competition_indicator'],-r['housing_photos_within_2km']))
    # Two selected FSA recommendations should not effectively cover same catchment;
    # screen overlap with 8km minimum between representative candidate points.
    picks=[]
    for cand in sites:
        if cand['status']!='screened':continue
        if len({p['fsa'] for p in picks}|{cand['fsa']})!=len(picks)+1:continue
        if any(haversine((cand['latitude'],cand['longitude']),(p['latitude'],p['longitude']))<8 for p in picks):continue
        picks.append(cand)
        if len(picks)==2:break
    if len(picks)!=2:
        raise InvalidEvidence(
            f'Only {len(picks)} geographically distinct residential candidates were verified; '
            'cannot produce the required two recommendations or export a completed report. '
            'Review additional non-overlapping postal areas and housing evidence.')
    _export_csv(OUTPUT/'postal_area_comparison.csv',rows)
    _export_csv(OUTPUT/'candidate_locations.csv',sites)
    write_json(OUTPUT/'results.json',{'areas':rows,'candidate_points':sites,'two_distinct_candidates':picks,
         'method':'Local 2021 DA-weighted 5-km population and geolocated Google clinic counts; Psychology Today locally advertised postal listings per 10k full-FSA residents; combined competition indicator is the mean of these two distinct proxy rates, not a literal number of therapists; finalists require nearby verified housing photographs.',
         'limitations':'Google counts mapped businesses while PT counts directory profiles; combined ranking is a screening heuristic. Directories are incomplete and often overlap; 2021 population is a baseline, not 2026 growth. No unverified zeros are treated as supply.'})
    return {'rows':rows,'sites':sites,'two':picks}

def _export_csv(path,records):
    if not records:raise InvalidEvidence('No rows to export')
    with open(path,'w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0].keys()))
        writer.writeheader();writer.writerows(records)
