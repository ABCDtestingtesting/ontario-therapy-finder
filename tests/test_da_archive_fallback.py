"""Regression tests for live Statistics Canada DA ArcGIS 504 recovery."""
import zipfile
import shapefile
import pytest
from shapely.geometry import box, mapping
from shapely.ops import transform
from finder import census
from finder.common import SourceUnavailable, InvalidEvidence


def make_archive(tmp_path,missing_dbf=False):
    root=tmp_path/'source'; root.mkdir(exist_ok=True)
    prefix=root/'lda_000b21a_e'
    with shapefile.Writer(str(prefix)) as writer:
        writer.field('DAUID','C',8)
        a=transform(census.project(),box(-79.84,43.70,-79.82,43.72))
        b=transform(census.project(),box(-81.1,44.0,-81.08,44.02))
        for uid,geom in (('35200001',a),('35200002',b)):
            writer.record(uid)
            writer.poly([list(geom.exterior.coords)])
    archive=tmp_path/'lda_000b21a_e.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for ext in ('.shp','.shx','.dbf'):
            if ext!='.dbf' or not missing_dbf:z.write(prefix.with_suffix(ext),arcname='lda_000b21a_e'+ext)
    return archive


def test_da_archive_selects_geographic_overlap_and_preserves_real_coordinates(tmp_path,monkeypatch):
    monkeypatch.setattr(census,'DATA',tmp_path)
    archive=make_archive(tmp_path)
    # Only synthetic record count is relaxed in this deliberately tiny fixture.
    real_reader=shapefile.Reader
    class SmallReader(real_reader):
        def __len__(self):return max(20000,super().__len__())
    monkeypatch.setattr(shapefile,'Reader',SmallReader)
    result=census._parse_da_shapefile_archive(archive,(-79.9,43.65,-79.75,43.75))
    assert set(result)=={'35200001'}
    p=census.representative(result['35200001'])
    assert abs(p[0]-43.71)<.01 and abs(p[1]+79.83)<.01


def test_da_missing_shapefile_component_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(census,'DATA',tmp_path)
    archive=make_archive(tmp_path,missing_dbf=True)
    with pytest.raises(InvalidEvidence,match='missing .dbf'):
        census._parse_da_shapefile_archive(archive,(-79.9,43.65,-79.75,43.75))


def test_da_arcgis_504_uses_official_archive_then_caches(tmp_path,monkeypatch):
    monkeypatch.setattr(census,'DATA',tmp_path)
    region=mapping(box(-79.85,43.68,-79.82,43.71))
    calls=[]
    def failure(*a,**kw):
        calls.append('arc'); raise SourceUnavailable('504 Gateway Timeout')
    monkeypatch.setattr(census,'load_layer',failure)
    monkeypatch.setattr(census,'_da_archive_fallback',lambda bbox,progress=None:{'35200001':region})
    first=census.da_near('L7A',region)
    assert first=={'35200001':region}
    assert census.da_near('L7A',region).keys()==first.keys()
    assert calls==['arc']


def test_da_archive_failure_does_not_cache_fake_zero(tmp_path,monkeypatch):
    monkeypatch.setattr(census,'DATA',tmp_path)
    region=mapping(box(-79.85,43.68,-79.82,43.71))
    monkeypatch.setattr(census,'load_layer',lambda *a,**kw: (_ for _ in ()).throw(SourceUnavailable('504')))
    monkeypatch.setattr(census,'_da_archive_fallback',lambda *a,**kw: (_ for _ in ()).throw(SourceUnavailable('archive offline')))
    with pytest.raises(SourceUnavailable,match='archive offline'):census.da_near('L7A',region)
    assert not (tmp_path/'da_boundaries'/'L7A.json').exists()
