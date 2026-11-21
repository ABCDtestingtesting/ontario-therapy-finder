"""Fast local setup checks, not a substitute for live external source validation."""
import sys
from pathlib import Path
from .common import ROOT,DATA,read_json,write_json
from . import census,maps,psychology_today,rank,housing

def run():
    assert sys.version_info >= (3,11)
    assert census.FSA_LAYER.endswith('/14/query') and census.DA_LAYER.endswith('/12/query')
    assert len(maps.SEARCHES)>=5 and 'google' in str(maps.RELEASE_URL)
    assert psychology_today.extract('<html><body>hi</body></html>','L7A')['profiles']==[]
    assert rank.haversine((43.25,-79.87),(43.25,-79.87))==0
    for folder in (DATA,ROOT/'output',ROOT/'logs'):
        assert folder.is_dir() and folder.exists(),str(folder)
    from .server import app
    assert app is not None
    print('PASS: Python, dependencies, writable folders, census layers, data parsers, server startup',flush=True)
if __name__=='__main__':run()
