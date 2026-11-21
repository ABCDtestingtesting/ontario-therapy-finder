"""Regression tests added after V4 audit. Tests are local, not live-web certification."""
import csv
import stat
import sys
import time
from pathlib import Path
import pytest
from shapely.geometry import box, mapping
from finder import maps, psychology_today, housing
from finder.common import SourceUnavailable


def test_postal_listing_is_never_inferred_to_offer_in_person_therapy():
    html = '''<html><body><h2>Number of Counsellors in L7A 2+</h2>
      <article class="card"><a href="/ca/therapists/local-name/324578">Local Name</a>
      <span>Brampton, ON L7A</span><p>Offers counselling to adults in Ontario.</p></article>
      <article class="card"><a href="/ca/therapists/remote-name/324579">Remote Name</a>
      <span>Online Only</span><p>Therapy sessions available online only.</p></article></body></html>'''
    result = psychology_today.extract(html, 'L7A')
    kinds = {p['id']:p['kind'] for p in result['profiles']}
    assert kinds['324578'] == 'local_postal_listing'
    assert kinds['324579'] == 'online_only'
    assert 'in_person_local_fsa' not in kinds.values()


def test_cancellation_before_pt_navigation_keeps_checkpoint(monkeypatch,tmp_path):
    monkeypatch.setattr(psychology_today,'DATA',tmp_path)
    with pytest.raises(SourceUnavailable,match='stopped by user'):
        psychology_today.collect('L7A',cancel_requested=lambda:True)
    checkpoint=psychology_today.read_json(tmp_path/'areas'/'L7A'/'pt'/'checkpoint.json')
    assert checkpoint['status']=='stopped_by_user'
    assert checkpoint['next_page']==1


def test_real_subprocess_cancel_and_resume_data_kept(monkeypatch,tmp_path):
    monkeypatch.setattr(maps,'DATA',tmp_path)
    exe=tmp_path/'fake-google-engine'
    exe.write_text('#!'+sys.executable+'\nimport sys,time,csv\n'
        'out=sys.argv[sys.argv.index("-results")+1]\n'
        'with open(out,"w") as f:\n'
        ' f.write("title,latitude,longitude,link,place_id\\n")\n'
        ' f.write("Therapy clinic,43.7,-79.83,https://google.com/maps/place/foo,foo\\n")\n'
        ' f.flush()\n'
        'time.sleep(30)\n')
    exe.chmod(exe.stat().st_mode|stat.S_IXUSR)
    monkeypatch.setattr(maps,'ensure_binary',lambda progress:exe)
    started=time.monotonic()
    with pytest.raises(SourceUnavailable,match='stopped by user'):
        maps.execute('L7A',mapping(box(-79.85,43.68,-79.82,43.71)),
                     cancel_requested=lambda:time.monotonic()-started>0.25)
    folder=tmp_path/'areas'/'L7A'/'google'
    assert (folder/'google_raw.csv').exists()
    assert not (folder/'locations.json').exists()
    assert time.monotonic()-started<8


def test_missing_housing_cannot_be_automatically_approved():
    report={'samples':[{'status':'captured_pending_review','point':{'id':'35200001','lat':43.7,'lon':-79.8},
                        'human_review':{'category':'unknown','note':'Unable to see housing'}},
                       {'status':'needs_retry','point':{'id':'35200002'},
                        'human_review':{'category':'detached'}}]}
    assert housing.count_reviewed(report)==0
    assert housing.contextual_housing(report,43.7,-79.8)['photos']==0


def test_google_parse_does_not_turn_invalid_source_row_into_zero(tmp_path):
    data=tmp_path/'google.csv'
    data.write_text('title,latitude,longitude,link,place_id\n'
                    'Good,43.7,-79.83,https://google.com/maps/place/a,a\n'
                    'Bad,,,https://google.com/maps/place/b,b\n')
    with pytest.raises(Exception,match='lacked valid coordinates'):
        maps.parse_csv(data)
