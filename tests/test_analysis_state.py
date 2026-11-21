import json,csv
from pathlib import Path
from shapely.geometry import mapping,box
import pytest
from finder import state,rank,census
from finder.common import DATA,OUTPUT,write_json,InvalidEvidence,Incomplete

AREAS={'L7A':(43.7,-79.83),'N1T':(43.36,-80.28)}

def geographic_fixture():
    geos={};population={};fsa_geos={};
    for code,(lat,lon) in AREAS.items():
        fsa_geos[code]=mapping(box(lon-.014,lat-.014,lon+.014,lat+.014))
        for i,(dx,dy) in enumerate(((-.012,-.012),(.002,-.012),(-.012,.002),(.002,.002))):
            uid=('3520' if code=='L7A' else '3530')+f'{i:04d}'
            geos[uid]=mapping(box(lon+dx,lat+dy,lon+dx+.01,lat+dy+.01))
            population[uid]={'population':700,'occupied':270,'dwellings':280}
    return fsa_geos,geos,population

@pytest.fixture
def geo(monkeypatch):
    from finder import census
    fsas,das,pop=geographic_fixture()
    monkeypatch.setattr(census,'fsa_geometry',lambda progress=None:fsas)
    monkeypatch.setattr(census,'da_near',lambda fsa,g,progress=None,pad_km=6.2:{k:v for k,v in das.items() if k.startswith('3520' if fsa=='L7A' else '3530')})
    monkeypatch.setattr(census,'load_population',lambda kind,progress=None:pop if kind=='da' else {
        code:{'population':2800,'occupied':1080} for code in AREAS})
    return fsas,das,pop

def populate_approved(geo):
    fsas,das,pop=geo
    for code,(lat,lon) in AREAS.items():
        payload=census.catchment(lat,lon,{k:v for k,v in das.items() if k.startswith('3520' if code=='L7A' else '3530')},pop)
        state.stage(code,'population','verified',payload)
        places={'locations':[{'id':code,'lat':lat,'lon':lon,'name':'Office '+code,'url':'https://www.google.com/maps/place/test','address':'123 test'}]}
        path=DATA/'areas'/code/'google'/'locations.json'
        write_json(path,places)
        state.stage(code,'google','verified',places)
        pt={'unique_profiles':2,'directory_total':{'lower_bound':2,'rounded':False},
            'classes':{'local_postal_listing':1,'online_only':1,'serves_area':0,'unknown':0},'source_url':'https://psychologytoday.com'}
        state.stage(code,'psychology_today','verified',pt)
        samples=[{'status':'captured_pending_review','human_review':{'category':'townhouse','note':'Residential housing'},
                  'point':{'id':f'sample{i}', 'lat':lat, 'lon':lon},
                  'url':f'https://www.google.com/maps/@?viewpoint={lat},{lon}' } for i in range(7)]
        state.stage(code,'housing','verified',{'samples':samples})

def test_incomplete_always_blocks_export(geo):
    if (OUTPUT/'postal_area_comparison.csv').exists(): (OUTPUT/'postal_area_comparison.csv').unlink()
    with pytest.raises(Incomplete,match='Incomplete'):
        rank.analyse(['L7A','N1T'])
    assert not (OUTPUT/'postal_area_comparison.csv').exists()

def test_all_four_sources_generate_street_output_and_distinct_candidates(geo):
    populate_approved(geo)
    out=rank.analyse(['L7A','N1T'])
    assert len(out['rows'])==2 and len(out['sites'])>=8
    assert set(x['fsa'] for x in out['two'])=={'L7A','N1T'}
    assert (OUTPUT/'candidate_locations.csv').exists()
    assert (OUTPUT/'results.json').exists()
    assert out['sites'][0]['population_5km_2021_est']>0
    assert all(r['pt_unique_profiles']==2 for r in out['rows'])

def test_housing_source_without_reviews_blocks(geo):
    populate_approved(geo)
    state.stage('L7A','housing','review_required',{'samples':[{'status':'captured_pending_review'}]})
    with pytest.raises(Incomplete):rank.analyse(['L7A'])

def test_point_distance_logic():
    assert rank.haversine((43.25,-79.87),(43.25,-79.87))==0
    assert 70<rank.haversine((43.25,-79.87),(43.8,-80.4))<90

def test_merge_locations_deduplicates_across_areas(geo):
    populate_approved(geo)
    p=DATA/'areas'/'N1T'/'google'/'locations.json'
    write_json(p,{'locations':[{'id':'L7A','lat':43.7,'lon':-79.83,'name':'Same office'}]})
    assert len(rank.merged_locations(['L7A','N1T']))==1

def test_interrupted_job_marked_resumeable():
    state.job('running','Scan N1T')
    state.stage('N1T','google','running',{'old_rows':10})
    state.mark_interrupted_jobs()
    d=state.read()
    assert d['job']['status']=='interrupted'
    assert d['areas']['N1T']['google']['status']=='interrupted'
    assert d['areas']['N1T']['google']['evidence']['old_rows']==10


def test_job_progress_does_not_overwrite_parent_task():
    state.job('running','Download official Statistics Canada census sources')
    state.progress('Parsing first geography')
    r=state.read()['job']
    assert r['message']=='Download official Statistics Canada census sources'
    assert r['progress']=='Parsing first geography'

def test_unknown_housing_photo_does_not_count_as_residential():
    from finder import housing
    samples=[{'status':'captured_pending_review','human_review':{'category':'unknown'}},
             {'status':'captured_pending_review','human_review':{'category':'undeveloped'}},
             {'status':'captured_pending_review','human_review':{'category':'townhouse'}}]
    assert housing.count_reviewed({'samples':samples})==1

def test_housing_affects_candidate_selection(geo):
    populate_approved(geo)
    s=state.read()['areas']['L7A']['housing']['evidence']
    for photo in s['samples']:
        photo['point']['lat']=0.0;photo['point']['lon']=0.0
    state.stage('L7A','housing','verified',s)
    # An incomplete source must never result in one recommendation labelled as two.
    with pytest.raises(InvalidEvidence,match='Only 1 geographically distinct'):
        rank.analyse(['L7A','N1T'])


def test_one_postal_area_never_creates_a_two_recommendation_export(geo):
    populate_approved(geo)
    for name in ('postal_area_comparison.csv','candidate_locations.csv','results.json'):
        (OUTPUT/name).unlink(missing_ok=True)
    with pytest.raises(InvalidEvidence,match='At least two distinct postal areas'):
        rank.analyse(['L7A'])
    assert not (OUTPUT/'results.json').exists()


def test_two_areas_without_two_eligible_sites_do_not_export(geo):
    populate_approved(geo)
    hou=state.read()['areas']['L7A']['housing']['evidence']
    for photo in hou['samples']:
        photo['point']['lat']=0.0
        photo['point']['lon']=0.0
    state.stage('L7A','housing','verified',hou)
    for name in ('postal_area_comparison.csv','candidate_locations.csv','results.json'):
        (OUTPUT/name).unlink(missing_ok=True)
    with pytest.raises(InvalidEvidence,match='Only 1 geographically distinct'):
        rank.analyse(['L7A','N1T'])
    assert not (OUTPUT/'postal_area_comparison.csv').exists()
    assert not (OUTPUT/'candidate_locations.csv').exists()
    assert not (OUTPUT/'results.json').exists()
