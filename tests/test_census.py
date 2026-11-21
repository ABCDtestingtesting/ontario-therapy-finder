import csv,io,zipfile,json,math
from pathlib import Path
from shapely.geometry import mapping,box
import pytest
from finder import census
from finder.common import InvalidEvidence
HEADERS=['REF_DATE','GEO','DGUID',
 'Population and dwelling counts (3): Population, 2021 [1]',
 'Population and dwelling counts (3): Total private dwellings, 2021 [2]',
 'Population and dwelling counts (3): Private dwellings occupied by usual residents, 2021 [3]']

def archive(tmp_path,kind,rows):
    file=tmp_path/f'{kind}.zip'
    content=io.StringIO();w=csv.writer(content);w.writerow(HEADERS)
    for row in rows:w.writerow(row)
    with zipfile.ZipFile(file,'w') as z:z.writestr('98100019.csv',content.getvalue())
    return file

def test_official_wide_fsa(tmp_path):
    z=archive(tmp_path,'fsa',[('2021','L7A','2021S0510L7A','104009','35000','32000'),('2021','N1T','','40000','18000','16000')])
    d=census.parse_zip(z,'fsa',min_rows=2)
    assert d['L7A']['population']==104009 and d['L7A']['occupied']==32000
    assert d['N1T']['dwellings']==18000

def test_official_wide_da_dguid(tmp_path):
    z=archive(tmp_path,'da',[('2021','Toronto Ontario [35200001]','2021S051235200001','500','300','200')])
    d=census.parse_zip(z,'da',min_rows=1)
    assert d['35200001']['population']==500

def test_missing_columns_rejected(tmp_path):
    file=tmp_path/'bad.zip'
    with zipfile.ZipFile(file,'w') as z:z.writestr('bad.csv','GEO,DGUID,VALUE\nL7A,,123\n')
    with pytest.raises(InvalidEvidence,match='schema'):census.parse_zip(file,'fsa',1)

def test_truncated_or_suppressed_data_cannot_become_zero(tmp_path):
    z=archive(tmp_path,'fsa',[('2021','L7A','','x','100','60')])
    with pytest.raises(InvalidEvidence,match='Incomplete census'):census.parse_zip(z,'fsa',min_rows=1)

def test_duplicate_conflicting_population_rejected(tmp_path):
    z=archive(tmp_path,'fsa',[('2021','L7A','','100','50','45'),('2021','L7A','','200','50','45')])
    with pytest.raises(InvalidEvidence,match='Conflicting'):census.parse_zip(z,'fsa',1)

def test_invalid_zip(tmp_path):
    f=tmp_path/'a.zip';f.write_bytes(b'broken')
    with pytest.raises(zipfile.BadZipFile):census.parse_zip(f,'fsa',1)

def test_population_catchment_overlap():
    g={'35200001':mapping(box(-79.91,43.24,-79.89,43.26)),
       '35200002':mapping(box(-79.89,43.24,-79.87,43.26))}
    p={'35200001':{'population':400,'occupied':200},'35200002':{'population':600,'occupied':250}}
    x=census.catchment(43.25,-79.89,g,p,5)
    assert x['population_2021_estimate']==1000 and x['occupied_dwellings_2021_estimate']==450

def test_catchment_requires_every_intersecting_da():
    g={'35200001':mapping(box(-79.9,43.24,-79.89,43.26))}
    with pytest.raises(InvalidEvidence,match='Missing population'):census.catchment(43.25,-79.89,g,{},5)

def test_nonzero_population_required():
    g={'35200001':mapping(box(-79.9,43.24,-79.89,43.26))}
    with pytest.raises(InvalidEvidence,match='Missing positive population'):census.catchment(43.25,-79.89,g,{'35200001':{'population':0,'occupied':0}},5)

def test_arcgis_paginated_count_exact(monkeypatch):
    calls=[]
    def fake(url,p):
        calls.append(p.copy())
        if p.get('returnCountOnly'):return {'count':3}
        first=p['resultOffset'];remaining=min(p['resultRecordCount'],3-first)
        return {'type':'FeatureCollection','features':[{'properties':{'CFSAUID':'L7'+chr(65+i)},
          'geometry':mapping(box(-79.9+i*.02,43.2,-79.89+i*.02,43.21))} for i in range(first,first+remaining)]}
    monkeypatch.setattr(census,'_arc_json',fake)
    x=census.load_layer('fake',"PRUID='35'",'CFSAUID')
    assert len(x)==3 and len(calls)==2

def test_arcgis_incomplete_page_rejected(monkeypatch):
    monkeypatch.setattr(census,'_arc_json',lambda url,p: {'count':5} if p.get('returnCountOnly') else {'type':'FeatureCollection','features':[]})
    with pytest.raises(InvalidEvidence,match='empty page'):census.load_layer('fake','1=1','DAUID')

def test_representative_inside_polygon():
    geometry=mapping(box(-80,43,-79.5,43.5))
    lat,lon=census.representative(geometry)
    assert 43<lat<43.5 and -80<lon<-79.5
