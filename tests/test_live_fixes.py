from shapely.geometry import mapping,box
from finder import census,google_browser
from finder.common import SourceUnavailable


def test_statcan_server_error_during_large_request_halves_batches(monkeypatch):
    requests=[]
    def query(url,params):
        if params.get('returnCountOnly'):
            return {'count':5}
        requests.append((params['resultOffset'],params['resultRecordCount']))
        if params['resultRecordCount']>2:
            raise SourceUnavailable('HTTP 500 response for large polygon page')
        first=params['resultOffset'];size=params['resultRecordCount']
        return {'type':'FeatureCollection', 'features':[
            {'properties':{'CFSAUID':f'L{i:02d}'},'geometry':mapping(box(-80+i*.02,43,-79.99+i*.02,43.01))}
            for i in range(first,first+size)]}
    monkeypatch.setattr(census,'_arc_json',query)
    results=census.load_layer('mock',"PRUID='35'",'CFSAUID')
    assert len(results)==5
    assert (0,5) in requests and (0,2) in requests
    assert set(results)=={'L00','L01','L02','L03','L04'}


def test_no_region_coordinates_from_map_viewport():
    assert google_browser.place_coordinates('https://www.google.com/maps/place/Clinic/@43.25,-79.8,15z') is None


def test_place_coordinate_detail_page_resolution():
    class Locator:
        def count(self):return 0
    class Tab:
        url='https://www.google.com/maps/place/Test+Clinic/data=!3d43.25123!4d-79.85123'
        def goto(self,*args,**kwargs):pass
        def locator(self,*args):return Locator()
        def close(self):pass
    class Context:
        def new_page(self):return Tab()
    coords,url=google_browser.resolve_place_coordinates(Context(),'https://www.google.com/maps/place/Test+Clinic')
    assert coords==(43.25123,-79.85123)
    assert '!3d' in url


def test_real_shapefile_archive_fallback_preserves_coordinates(monkeypatch,tmp_path):
    import zipfile,shapefile
    from pathlib import Path
    monkeypatch.setattr(census,'DATA',tmp_path)
    prefix=tmp_path/'lfsa000b21a_e'
    def ring(center):
        lat,lon=center
        coords=[(lon-.008,lat-.008),(lon+.008,lat-.008),
                (lon+.008,lat+.008),(lon-.008,lat+.008),(lon-.008,lat-.008)]
        return [census.project()(x,y) for x,y in coords]
    with shapefile.Writer(str(prefix),shapeType=shapefile.POLYGON) as writer:
        writer.field('CFSAUID','C',size=3)
        writer.field('PRUID','C',size=2)
        for code,lat,lon in [('L7A',43.72,-79.82),('L6Z',43.70,-79.80),('N1T',43.38,-80.27)]:
            writer.poly([ring((lat,lon))])
            writer.record(code,'35')
    archive=tmp_path/'archive.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for ext in ('.shp','.shx','.dbf'):
            z.write(str(prefix)+ext,arcname='folder/lfsa000b21a_e'+ext)
    data=census._parse_fsa_shapefile_archive(archive,minimum=3)
    assert set(data)=={'L7A','L6Z','N1T'}
    lat,lon=census.representative(data['L7A'])
    assert abs(lat-43.72)<.03 and abs(lon+79.82)<.03


def test_primary_census_geometry_uses_archive_before_arcgis(monkeypatch,tmp_path):
    from finder import census
    from shapely.geometry import mapping,box
    monkeypatch.setattr(census,'DATA',tmp_path)
    # Generate a full-size Ontario set of synthetic but valid FSA boundaries.
    data={f'L{(i//26)%10}{chr(65+i%26)}':mapping(box(-80,43,-79,44)) for i in range(260)}
    data.update({f'N{(i//26)%10}{chr(65+i%26)}':mapping(box(-80,43,-79,44)) for i in range(260)})
    monkeypatch.setattr(census,'_fsa_archive_fallback',lambda progress=None:data)
    monkeypatch.setattr(census,'load_layer',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('ArcGIS called despite successful archive')))
    assert len(census.fsa_geometry())==520
