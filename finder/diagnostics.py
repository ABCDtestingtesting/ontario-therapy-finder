"""Create a compact troubleshooting report without copying therapist profiles or photos."""
from __future__ import annotations
import json, platform, sys, zipfile, datetime, importlib.metadata
from pathlib import Path
from .common import DATA,LOGS,OUTPUT,read_json
from . import __version__

PACKAGES=('fastapi','uvicorn','requests','beautifulsoup4','playwright','shapely','pyproj','pillow')

def build_report():
    job=read_json(DATA/'run_state.json',{})
    areas={code:{source:{'status':record.get('status'),'error':record.get('error')}
                for source,record in val.items() if isinstance(record,dict) and 'status' in record}
           for code,val in job.get('areas',{}).items()}
    versions={}
    for package in PACKAGES:
        try:versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:versions[package]='missing'
    report={'app_version':__version__, 'operating_system':platform.platform(),
            'python':sys.version.split()[0], 'package_versions':versions,
            'data_files':{key:(DATA/key).is_file() for key in ('fsa_population.json','da_population.json','fsa_boundaries.json')},
            'last_job':job.get('job',{}),'areas':areas}
    return report

def write_report():
    now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=OUTPUT/f'diagnostics_{now}.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('status.json',json.dumps(build_report(),indent=2))
        for file in (LOGS/'last_error.log',LOGS/'maps_installer.log'):
            if file.is_file():bundle.writestr('logs/'+file.name,file.read_text(errors='replace')[-50000:])
        # No page HTML, Street View photos, cached profiles or complete Google CSV.
        for area in (DATA/'areas').glob('*') if (DATA/'areas').is_dir() else []:
            log=area/'google'/'collector.log'
            if log.is_file():bundle.writestr(f'logs/google_{area.name}.log',log.read_text(errors='replace')[-10000:])
    return target

if __name__=='__main__':print('Diagnostic report saved:',write_report(),flush=True)
