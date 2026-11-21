"""Live macOS probes for the actual Ontario Therapy Finder package.

No simulation. A probe is considered passed only after the required external call
returns a validated result. Browser/Maps failures remain failures with diagnostics.
"""
from __future__ import annotations
import argparse, json, os, platform, subprocess, tempfile, time, sys
from pathlib import Path
from urllib.parse import urlparse
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def log(*parts):
    print(*parts, flush=True)


def app_probe():
    from finder.server import app
    import uvicorn
    import socket
    import urllib.request
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with (ROOT/'ci'/'app_server.log').open('w') as server_log:
        proc = subprocess.Popen([sys.executable,'-m','uvicorn','finder.server:app',
                                 '--host','127.0.0.1','--port',str(port)],
                                cwd=ROOT,env=env,stdout=server_log,stderr=subprocess.STDOUT)
        try:
            for _ in range(50):
                if proc.poll() is not None:
                    raise RuntimeError(f'HTTP server exited early with code {proc.returncode}')
                try:
                    health=requests.get(f'http://127.0.0.1:{port}/health',timeout=2)
                    if health.ok:break
                except requests.RequestException:pass
                time.sleep(.2)
            else:raise RuntimeError('HTTP server did not start in 10 seconds')
            for name in ('/','/health','/api/status'):
                r=requests.get(f'http://127.0.0.1:{port}{name}',timeout=10)
                if r.status_code!=200:raise RuntimeError(f'{name}: HTTP {r.status_code}')
                if name != '/':
                    data=r.json()
                    if data.get('ok') is not True:raise RuntimeError(f'{name}: JSON response missing ok=true')
                elif 'html' not in r.headers.get('Content-Type','').lower():
                    raise RuntimeError('Dashboard root did not return HTML')
                log(f'PASS real localhost {name}: {r.status_code}')
        finally:
            proc.terminate()
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()



def mac_launcher_probe():
    """Run the real user-facing zsh launcher on a hosted Mac and query its server."""
    if platform.system()!='Darwin':
        raise RuntimeError('Launcher live test requires real macOS')
    import signal
    launch_log=ROOT/'ci'/'real_launcher.log'
    with launch_log.open('w',encoding='utf8') as f:
        proc=subprocess.Popen(['/bin/zsh','start.command'],cwd=ROOT,stdin=subprocess.DEVNULL,
                              stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f'start.command exited {proc.returncode} before launching; inspect ci/real_launcher.log')
                try:
                    r=requests.get('http://127.0.0.1:8765/health',timeout=2)
                    if r.status_code==200 and r.json().get('ok') is True:
                        page=requests.get('http://127.0.0.1:8765/',timeout=5)
                        if page.status_code != 200:raise RuntimeError('Launcher dashboard was not HTTP 200')
                        log('Real start.command launched dashboard and /health passed')
                        return
                except (requests.RequestException,ValueError):pass
                time.sleep(2)
            raise RuntimeError('Real Mac launcher did not provide a working server within 10 minutes')
        finally:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()


def census_probe():
    from finder import census
    fsa=census.load_population('fsa',log)
    da=census.load_population('da',log)
    boundaries=census.fsa_geometry(log)
    code='L7A'
    if code not in fsa or code not in boundaries:raise RuntimeError('L7A missing from census source')
    neighbours=census.da_near(code,boundaries[code],log)
    pos=census.representative(boundaries[code])
    catch=census.catchment(*pos,neighbours,da)
    log(f'FSA records={len(fsa)}; DA population records={len(da)}; boundaries={len(boundaries)}')
    log(f'L7A: population={fsa[code]["population"]}; nearby_DAs={len(neighbours)}; catchment={catch}')
    if not neighbours or not catch or not any(isinstance(v,(float,int)) and v>0 for v in catch.values()):
        raise RuntimeError('No validated populated L7A catchment')


def maps_probe():
    """Real Google Maps search through Firefox, no API key or Go dependency."""
    from finder.google_browser import scan_one
    from finder.common import DATA
    from playwright.sync_api import sync_playwright
    folder=DATA/'ci_google_firefox';folder.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        ctx=pw.firefox.launch_persistent_context(str(folder/'profile'),headless=True,
                   viewport={'width':1400,'height':960},locale='en-CA')
        try:
            result=scan_one(ctx,'psychotherapist',43.250,-79.871,folder,timeout_seconds=105)
        finally:ctx.close()
    sites=result['place_links']
    print('Actual Google Maps search:',result['completion_reason'],
        'places=',len(sites),'with verified coordinates=',sum(bool(x['coordinates']) for x in sites))
    if not sites:
        raise RuntimeError('Actual Google Maps returned zero places; cannot certify collector')
    if not any(x['coordinates'] for x in sites):
        raise RuntimeError('Actual Google Maps search had no place coordinates')


def pt_probe():
    from finder import psychology_today as pt
    from playwright.sync_api import sync_playwright
    from finder.common import DATA
    # CI is unattended; use the same Firefox engine with its visible profile, headless.
    # A challenge or unexpected HTML MUST fail; the screenshot is retained.
    def factory(pw, profile):
        return pw.firefox.launch_persistent_context(profile,headless=True,
                 viewport={'width':1300,'height':900},locale='en-CA')
    result=pt.collect('L7A',log,max_pages=100,context_factory=factory)
    count=result['unique_profiles']
    lower=result['directory_total']['lower_bound']
    log(f'Live PT L7A: {count} unique profiles, directory lower bound {lower}, pages {len(result["pages"])}')
    if count<lower or not result['pages']:
        raise RuntimeError('PT directory result not complete')


def housing_probe():
    from finder import census,housing
    from finder.common import DATA
    if not (DATA/'da_population.json').exists():
        raise RuntimeError('Run census first: DA population data missing')
    populations=census.load_population('da')
    geos=census.fsa_geometry()
    neighbours=census.da_near('L7A',geos['L7A'],log)
    points=housing.sample_points(geos['L7A'],neighbours,populations,limit=12)
    if len(points)<3:raise RuntimeError('No populated residential DA sample points')
    def factory(pw):
        return pw.firefox.launch_persistent_context(str(DATA/'ci_housing_browser'),
             headless=True,viewport={'width':1365,'height':880})
    report=housing.capture('CIH',points,log,max_usable=2,minimum_usable=1,
                           context_factory=factory)
    captured=[r for r in report['samples'] if r['status']=='captured_pending_review']
    if not captured:raise RuntimeError('No live Street View screenshot usable')
    for r in captured:log('PHOTO CAPTURED, REVIEW STILL REQUIRED:',r.get('image'),r.get('url'))
    log('This test proves screenshot capture only. It does not certify housing classification.')


PROBES={'app':app_probe,'mac_launcher':mac_launcher_probe,'census':census_probe,'maps':maps_probe,
        'psychology_today':pt_probe,'housing_capture':housing_probe}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=PROBES)
    args=parser.parse_args()
    log('MAC LIVE TEST:',args.stage,'platform:',platform.platform(),
        'machine:',platform.machine(),'python:',sys.version.split()[0])
    PROBES[args.stage]()
    log('PASSED LIVE TEST:',args.stage)

if __name__=='__main__':main()
