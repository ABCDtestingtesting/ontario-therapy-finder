import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from finder import server,state,housing
from finder.common import DATA,write_json
app=TestClient(server.app)

def test_home_and_health_api():
    assert app.get('/').status_code==200
    assert 'censusButton' in app.get('/').text
    for path in ('/health','/api/status'):
        j=app.get(path).json();assert j['ok'] is True and j['version']=='5.1.0'

def test_invalid_areas_do_not_start_scan():
    response=app.post('/api/run',json={'areas':'NOT_A_CODE'})
    assert response.status_code==409 and response.json()['ok'] is False

def test_missing_census_returns_immediate_message(monkeypatch):
    monkeypatch.setattr(server,'census_health',lambda:{'ready':False})
    r=app.get('/api/eligible')
    assert r.status_code==409 and 'Census data are missing' in r.json()['error']
    r=app.post('/api/run',json={'areas':'L7A'})
    assert r.status_code==409 and 'census' in r.json()['error'].lower()

def test_bad_review_has_consistent_error():
    for source in ('google','psychology_today','housing'):
        r=app.post('/api/approve',json={'fsa':'L7A','source':source,'note':'A useful text note about the source'})
        assert r.status_code==409 and r.json()['ok'] is False

def test_evidence_endpoint_errors_not_http200():
    r=app.get('/api/evidence/XYZ/google')
    assert r.status_code==404 and r.json()['ok'] is False

def test_rank_refuses_incomplete():
    r=app.post('/api/rank',json={'areas':'L7A'})
    assert r.status_code==409 and r.json()['ok'] is False

def test_private_app_files_not_exposed():
    p=DATA/'secret.json';p.write_text('{"private":1}')
    assert app.get('/data/data/secret.json').status_code==404
    assert app.get('/data/../../etc/passwd').status_code in (400,404)

def test_stale_port_chooses_fresh_port():
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        occupied=sock.getsockname()[1]
        port=server.free_port(preferred=occupied)
        assert port!=occupied and port>0

def test_good_photo_review_endpoint(monkeypatch,tmp_path):
    from PIL import Image
    monkeypatch.setattr(housing,'DATA',tmp_path)
    folder=tmp_path/'areas'/'L7A'/'housing';folder.mkdir(parents=True)
    photo=folder/'x.png';Image.new('RGB',(1365,880),'red').save(photo)
    write_json(folder/'manifest.json',{'samples':[{'point':{'id':'35200001'},'status':'captured_pending_review','image':str(photo)}]})
    r=app.post('/api/photo-review',json={'fsa':'L7A','uid':'35200001','category':'townhouse','note':'Several residential buildings visible'})
    assert r.status_code==200 and r.json()['ok'] is True


def test_polled_status_does_not_leak_all_directory_contents():
    state.stage('L7A','psychology_today','review_required',{'profiles':[{'name':'A private example'}],
                                     'unique_profiles':1})
    r=app.get('/api/status')
    assert r.status_code==200 and r.json()['ok']
    assert r.json()['state']['areas']['L7A']['psychology_today']['status']=='review_required'
    assert 'A private example' not in r.text

def test_housing_photo_actual_browser_url_is_served(tmp_path):
    from PIL import Image
    path=DATA/'areas'/'L7A'/'housing'/'photo_test.png'
    path.parent.mkdir(parents=True,exist_ok=True)
    Image.new('RGB',(1000,600),'blue').save(path)
    write_json(DATA/'areas'/'L7A'/'housing'/'manifest.json',
        {'samples':[{'point':{'id':'35200001'},'status':'captured_pending_review','image':str(path)}]})
    r=app.get('/api/photo/L7A/35200001')
    assert r.status_code==200 and r.headers['content-type']=='image/png'
