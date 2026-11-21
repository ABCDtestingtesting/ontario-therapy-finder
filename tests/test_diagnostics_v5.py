from pathlib import Path
import zipfile
from finder import diagnostics

def test_report_omits_source_profiles_and_photos(monkeypatch,tmp_path):
    monkeypatch.setattr(diagnostics,'DATA',tmp_path/'data')
    monkeypatch.setattr(diagnostics,'OUTPUT',tmp_path/'output')
    monkeypatch.setattr(diagnostics,'LOGS',tmp_path/'logs')
    for directory in (diagnostics.DATA,diagnostics.OUTPUT,diagnostics.LOGS):directory.mkdir()
    (diagnostics.DATA/'run_state.json').write_text('{"job":{"status":"failed","message":"site error"},"areas":{"L7A":{"google":{"status":"failed","evidence":{"private":"exclude me"}}}}}')
    (diagnostics.LOGS/'last_error.log').write_text('failed to download')
    outfile=diagnostics.write_report()
    with zipfile.ZipFile(outfile) as z:
        assert 'status.json' in z.namelist()
        assert 'logs/last_error.log' in z.namelist()
        assert 'exclude me' not in z.read('status.json').decode()
        assert not any('pages' in p or 'photo' in p for p in z.namelist())
