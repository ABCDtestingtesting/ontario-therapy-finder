import csv,json
import pytest
from shapely.geometry import mapping,box
from finder import maps
from finder.common import InvalidEvidence,SourceUnavailable

def make_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['title','latitude','longitude','link','place_id','address','category','status'])
        w.writeheader();w.writerows(rows)

def record(name='Clinic',lat='43.25',lon='-79.8',ident='foo'):
    return {'title':name,'latitude':lat,'longitude':lon,'link':'https://www.google.com/maps/place/'+name,
            'place_id':ident,'address':'Hamilton, ON','category':'Therapist','status':'open'}

def test_parse_dedup(tmp_path):
    p=tmp_path/'list.csv';make_csv(p,[record(),record(),record('Second','43.26','-79.81','bar')])
    x=maps.parse_csv(p)
    assert x['raw_rows']==3 and len(x['locations'])==2 and x['duplicates']==1

def test_invalid_coordinates_never_ignored(tmp_path):
    p=tmp_path/'list.csv';make_csv(p,[record(),record('Broken','','','bad')])
    with pytest.raises(InvalidEvidence,match='lacked valid coordinates'):maps.parse_csv(p)

def test_closed_not_counted(tmp_path):
    p=tmp_path/'list.csv';row=record();row['status']='Permanently closed';make_csv(p,[row])
    assert maps.parse_csv(p)['locations']==[]

def test_wrong_headers(tmp_path):
    f=tmp_path/'bad.csv';f.write_text('foo,bar\n1,2\n')
    with pytest.raises(InvalidEvidence,match='columns'):maps.parse_csv(f)

def test_asset_mac_arm_and_intel():
    assets=[{'name':'scraper_linux_amd64.tar.gz'},{'name':'google-maps-scraper_darwin_arm64.zip'},
            {'name':'google-maps-scraper_darwin_amd64.tar.gz'}]
    assert 'arm64' in maps.pick_release(assets,'Darwin','arm64')['name']
    assert 'amd64' in maps.pick_release(assets,'Darwin','x86_64')['name']
    assert maps.pick_release(assets,'Linux','arm64') is None

def test_execute_mock_collector(monkeypatch,tmp_path):
    monkeypatch.setattr(maps,'DATA',tmp_path)
    def runner(cmd,out):
        make_csv(out,[record()]);return 0
    result=maps.execute('L7A',mapping(box(-79.9,43.2,-79.87,43.24)),run_cmd=runner)
    assert result['raw_rows']==1 and len(result['locations'])==1
    assert (tmp_path/'areas'/'L7A'/'google'/'plan.json').exists()
    assert 'grid-bbox' in ' '.join(result['plan']['command'])
    assert '-exit-on-inactivity' not in result['plan']['command']

def test_failed_collector_never_creates_good_file(monkeypatch,tmp_path):
    monkeypatch.setattr(maps,'DATA',tmp_path)
    with pytest.raises(SourceUnavailable):maps.execute('L7A',mapping(box(-79.9,43.2,-79.87,43.24)),run_cmd=lambda cmd,out:9)
    assert not (tmp_path/'areas'/'L7A'/'google'/'locations.json').exists()

def test_resume_uses_same_plan(monkeypatch,tmp_path):
    monkeypatch.setattr(maps,'DATA',tmp_path)
    work=tmp_path/'areas'/'L7A'/'google';work.mkdir(parents=True)
    make_csv(work/'google_raw.csv',[record()])
    def runner(cmd,out):
        assert '-resume' in cmd;return 0
    x=maps.execute('L7A',mapping(box(-79.9,43.2,-79.87,43.24)),run_cmd=runner)
    assert len(x['locations'])==1
