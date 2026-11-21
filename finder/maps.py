"""Free open-source Google Maps collector adapter; source evidence is preserved.

No Google API key. Published gosom collector is an external prerequisite,
installed on first use. Failures cannot be interpreted as zero clinicians.
"""
from __future__ import annotations
import csv, json, platform, re, os, shutil, subprocess, tarfile, zipfile, time, signal
from pathlib import Path
from urllib.parse import urlsplit
import requests
from shapely.geometry import shape
from shapely.ops import transform
from .common import ROOT,DATA,BIN,LOGS,write_json,read_json,InvalidEvidence,SourceUnavailable,sha256
from .census import project,unproject
VERSION='v1.19.0'
RELEASE_URL=f'https://api.github.com/repos/gosom/google-maps-scraper/releases/tags/{VERSION}'
SEARCHES=('psychotherapist','counselling therapy','psychologist therapy',
          'registered social worker counselling','mental health clinic','trauma therapy')

def binary():return BIN/'google-maps-scraper'
def command_works(path):
    try:
        r=subprocess.run([str(path),'-h'],capture_output=True,text=True,timeout=30)
        return r.returncode in (0,2) and '-input' in (r.stdout+r.stderr)
    except (OSError,subprocess.TimeoutExpired):return False

def pick_release(assets,system='Darwin',machine='arm64'):
    arch='arm64' if machine.lower() in ('arm64','aarch64') else 'amd64'
    def match(a):
        name=a.get('name','').lower()
        return any(k in name for k in ('darwin','macos','mac_','mac-')) and (
            arch in name or (arch=='amd64' and 'x86_64' in name) or (arch=='arm64' and 'aarch64' in name)) and not any(
                k in name for k in ('checksums','sha256','.sig'))
    return next((a for a in assets if match(a)),None) if system=='Darwin' else None

def _download(url,path):
    path.parent.mkdir(exist_ok=True,parents=True)
    with requests.get(url,stream=True,timeout=(20,180)) as r:
        r.raise_for_status()
        with path.open('wb') as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:f.write(chunk)
    if path.stat().st_size<10000:raise SourceUnavailable('Downloaded Google Maps binary is unexpectedly small')

def _safe_extract(archive,dirpath):
    dirpath.mkdir(parents=True,exist_ok=True);root=dirpath.resolve()
    def path(name):
        dst=(root/name).resolve()
        if dst!=root and root not in dst.parents:raise InvalidEvidence('Unsafe archive path')
        return dst
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                if item.is_dir():continue
                dest=path(item.filename);dest.parent.mkdir(parents=True,exist_ok=True)
                with z.open(item) as inp,dest.open('wb') as out:shutil.copyfileobj(inp,out)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive,'r:*') as t:
            for item in t:
                if not item.isfile():continue
                dest=path(item.name);dest.parent.mkdir(parents=True,exist_ok=True)
                with t.extractfile(item) as inp,dest.open('wb') as out:shutil.copyfileobj(inp,out)
    else:
        shutil.copyfile(archive,path(archive.name))
    return [p for p in root.rglob('*') if p.is_file()]

def ensure_binary(progress=lambda msg:None):
    exe=binary()
    if exe.exists() and command_works(exe):return exe
    exe.unlink(missing_ok=True)
    if platform.system()!='Darwin':
        sys_exe=shutil.which('google-maps-scraper')
        if sys_exe and command_works(sys_exe):return Path(sys_exe)
        raise SourceUnavailable('No compatible Google scraper. This installer targets macOS; tests can inject a fake collector.')
    try:
        progress('Checking pinned Google Maps collector release')
        r=requests.get(RELEASE_URL,timeout=40);r.raise_for_status()
        asset=pick_release(r.json().get('assets',[]),platform.system(),platform.machine())
        if asset:
            name=asset['name'];path=BIN/name
            progress('Downloading Google collector '+name)
            _download(asset['browser_download_url'],path)
            files=_safe_extract(path,BIN/'extracted')
            candidates=[p for p in files if re.search(r'google[-_]maps[-_]scraper|google-maps-scraper',p.name,re.I)]
            if not candidates:raise SourceUnavailable('Release did not contain identifiable Google scraper binary')
            shutil.copyfile(candidates[0],exe);exe.chmod(exe.stat().st_mode | 0o111)
            if command_works(exe):return exe
            exe.unlink(missing_ok=True)
            raise SourceUnavailable('Downloaded Google Maps binary did not pass its CLI self-test')
    except (requests.RequestException,OSError,ValueError,InvalidEvidence,SourceUnavailable) as e:
        progress('Release download unavailable: '+str(e)[:180]+'; checking source-build fallback')
    go=shutil.which('go') or '/opt/homebrew/bin/go'
    if not Path(go).exists():
        brew=shutil.which('brew') or '/opt/homebrew/bin/brew'
        if Path(brew).exists():
            progress('Installing free Go compiler (first run only)')
            with (LOGS/'maps_installer.log').open('a') as log:
                p=subprocess.run([brew,'install','go'],stdout=log,stderr=subprocess.STDOUT,timeout=2400)
            if p.returncode==0:go=shutil.which('go') or '/opt/homebrew/bin/go'
    if not Path(go).exists():
        raise SourceUnavailable('Google scraper unavailable: no Mac release and no Go compiler. Install Go from https://go.dev/dl/ or brew install go, then press Resume. No searches were marked complete.')
    git=shutil.which('git')
    if not git:raise SourceUnavailable('Git missing. Run xcode-select --install and try again.')
    source=BIN/'gosom_tag_source'
    with (LOGS/'maps_installer.log').open('a') as log:
        if not source.exists():
            progress('Downloading pinned Google scraper source')
            p=subprocess.run([git,'clone','--depth','1','--branch',VERSION,
                              'https://github.com/gosom/google-maps-scraper.git',str(source)],
                             stdout=log,stderr=subprocess.STDOUT,timeout=600)
            if p.returncode:raise SourceUnavailable('Google scraper source download failed; see logs/maps_installer.log')
        progress('Building Google Maps collector from pinned source')
        p=subprocess.run([go,'build','-o',str(exe),'.'],cwd=source,
                         stdout=log,stderr=subprocess.STDOUT,timeout=2400)
    if p.returncode or not exe.exists():raise SourceUnavailable('Google scraper build failed; see logs/maps_installer.log')
    exe.chmod(exe.stat().st_mode | 0o111)
    if not command_works(exe):raise SourceUnavailable('Google scraper build failed self-test')
    return exe

def bbox_with_margin(fsa_geometry,margin_m=5500):
    projected=transform(project(),shape(fsa_geometry)).buffer(margin_m)
    lonlat=transform(unproject(),projected)
    a,b,c,d=lonlat.bounds
    return f'{b:.6f},{a:.6f},{d:.6f},{c:.6f}'

def parse_csv(csvfile, require_geo=True):
    results={};rows=0;issues=[];closed=[]
    with open(csvfile,newline='',encoding='utf-8-sig') as fh:
        reader=csv.DictReader(fh)
        fields=set(reader.fieldnames or [])
        required={'title','latitude','longitude','link'}
        if not required<=fields:raise InvalidEvidence(f'Unexpected upstream Google CSV columns {sorted(fields)}')
        for row in reader:
            rows+=1
            name=(row.get('title') or '').strip();link=(row.get('link') or '').strip()
            try:lat=float(row.get('latitude',''));lon=float(row.get('longitude',''))
            except (TypeError,ValueError):lat=lon=None
            if not name or not link or lat is None or not (41<lat<57 and -96<lon<-73):
                issues.append({'row':rows,'reason':'name, link or Ontario coordinates missing'});continue
            status=row.get('status','')
            ident=(row.get('place_id') or row.get('cid') or row.get('data_id') or '').strip()
            if not ident:
                # Preserve near-identical names if they have distinct addresses.
                ident='composite:'+name.casefold()+'|'+(row.get('address') or '').casefold()+'|'+str(round(lat,5))+'|'+str(round(lon,5))
            if 'permanently closed' in status.lower():
                closed.append(ident);continue
            results[ident]={'id':ident,'name':name,'lat':lat,'lon':lon,'address':row.get('address',''),
                            'url':link,'website':row.get('website',''),'category':row.get('category',''),
                            'status':status,'source':'Google Maps','provider_kind':'location'}
    if require_geo and issues:
        raise InvalidEvidence(f'{len(issues)} Google listings lacked valid coordinates. Their locations must be checked. Rows: {issues[:8]}')
    return {'locations':list(results.values()),'raw_rows':rows,'duplicates':rows-len(results)-len(issues)-len(closed),
            'unlocated':issues,'closed':closed}

def execute(fsa,fsa_geometry,progress=lambda msg:None,run_cmd=None,force=False,cancel_requested=lambda:False):
    """Execute a saved, repeatable grid job. Native gosom resume sidecar retained."""
    folder=DATA/'areas'/fsa/'google';folder.mkdir(parents=True,exist_ok=True)
    normalized=folder/'locations.json'
    if normalized.exists() and not force:return read_json(normalized)
    if cancel_requested():
        raise SourceUnavailable('Google Maps search stopped before starting; saved work preserved')
    exe='google-maps-scraper' if run_cmd is None else 'fake-collector'
    bbox=bbox_with_margin(fsa_geometry)
    query_file=folder/'queries.txt';query_file.write_text('\n'.join(SEARCHES)+'\n',encoding='utf8')
    output=folder/'google_raw.csv'
    cmd=[str(exe),'-input',str(query_file),'-results',str(output),'-grid-bbox',bbox,
         '-grid-cell','1.0','-zoom','16','-depth','10','-c','2']
    if output.exists():cmd.insert(1,'-resume')
    spec={'collector':f'gosom/google-maps-scraper {VERSION}','bbox':bbox,'cell_km':1,
          'completion_policy':'No inactivity-based early exit; require collector successful process exit and manual grid review',
          'search_terms':list(SEARCHES),'command':cmd,'resume':output.exists()}
    old=read_json(folder/'plan.json',None)
    if old and old.get('bbox')!=bbox and output.exists():raise InvalidEvidence('Geographic search plan changed. Existing results cannot be safely resumed.')
    write_json(folder/'plan.json',spec)
    progress(f'{fsa}: scanning Google Maps grid (saved progress supported)')
    logfile=folder/'collector.log'
    firefox_issue=None
    # Start with the browser that is already installed by start.command. This
    # avoids requiring Go/Homebrew or an external native binary for a Mac where
    # regular Firefox can complete the search successfully.
    if run_cmd is None and os.environ.get('THERAPY_NATIVE_MAPS_FIRST')!='1':
        try:
            from .google_browser import collect as collect_firefox
            south,west,north,east=[float(n) for n in bbox.split(',')]
            collect_firefox((south,west,north,east),SEARCHES,output,
                            progress=progress,cancel_requested=cancel_requested)
            parsed=parse_csv(output)
            if not parsed['locations']:
                raise InvalidEvidence('Firefox produced no geolocated Google listings')
            parsed.update({'source_url':'https://www.google.com/maps/','plan':spec,
                 'raw_sha256':sha256(output),'sidecar_present':False,
                 'source_file':str(output),'manual_audit_needed':True,
                 'collector_used':'playwright-firefox','native_issue':None})
            write_json(normalized,parsed)
            return parsed
        except Exception as exc:
            if cancel_requested():
                raise SourceUnavailable('Google Maps scan stopped; saved Firefox progress preserved') from exc
            firefox_issue=str(exc)
            progress(f'{fsa}: Firefox collection incomplete ({exc}); checking native fallback')
    if run_cmd is None:
        try:exe=ensure_binary(progress)
        except (SourceUnavailable,InvalidEvidence) as exc:
            raise SourceUnavailable(f'No complete Google results. Firefox: {firefox_issue}; '
                        f'native prerequisite: {exc}') from exc
        cmd[0]=str(exe)
        spec['command']=cmd
        write_json(folder/'plan.json',spec)
    if run_cmd:
        rc=run_cmd(cmd,output)
    else:
        # Keep the process handle so the dashboard's Stop button can interrupt a
        # long grid scan instead of waiting up to ten hours. The scraper's CSV
        # and resume sidecar are never deleted on cancellation.
        with logfile.open('a',encoding='utf8') as log:
            proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            def stop_tree(sig):
                # Stop the scraper and its launched browser children together.
                # macOS and Linux support POSIX process groups.
                if hasattr(os,'killpg'):
                    try:os.killpg(proc.pid,sig)
                    except ProcessLookupError:pass
                else:
                    try:proc.send_signal(sig)
                    except ProcessLookupError:pass
            started=time.monotonic()
            try:
                while proc.poll() is None:
                    if cancel_requested():
                        stop_tree(signal.SIGTERM)
                        try:proc.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            stop_tree(signal.SIGKILL);proc.wait(timeout=8)
                        raise SourceUnavailable('Google Maps scan stopped by user; CSV and resume checkpoint preserved')
                    if time.monotonic()-started>36000:
                        stop_tree(signal.SIGTERM)
                        try:proc.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            stop_tree(signal.SIGKILL);proc.wait(timeout=8)
                        raise SourceUnavailable('Google Maps scan timed out; resume from saved CSV and sidecar')
                    time.sleep(0.75)
                rc=proc.returncode
            finally:
                if proc.poll() is None:
                    stop_tree(signal.SIGTERM)
                    try:proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:stop_tree(signal.SIGKILL);proc.wait(timeout=8)
    native_issue=None
    try:
        if rc!=0:
            raise SourceUnavailable(f'Google Maps native collector returned exit code {rc}')
        if not output.exists() or output.stat().st_size<30:
            raise InvalidEvidence('Google Maps native collector produced empty CSV')
        parsed=parse_csv(output)
        if parsed['raw_rows']==0 or not parsed['locations']:
            raise InvalidEvidence('Native collector returned no valid Google places')
        used='gosom-native'
    except (InvalidEvidence,SourceUnavailable) as exc:
        # A successful process exit is not evidence that the browser collected
        # any results. Use the independent Firefox engine for the same grid.
        if run_cmd is not None:
            raise
        native_issue=str(exc)
        progress(f'{fsa}: native Maps collector failed: {native_issue}. Trying Firefox collector.')
        from .google_browser import collect as collect_firefox
        south,west,north,east=[float(n) for n in bbox.split(',')]
        try:
            collect_firefox((south,west,north,east),SEARCHES,output,
                            progress=progress,cancel_requested=cancel_requested)
            parsed=parse_csv(output)
            used='playwright-firefox'
        except Exception as firefox_error:
            raise SourceUnavailable(
                f'Both Google collection methods failed. Native: {native_issue}; '
                f'Firefox: {firefox_error}. See {folder}/firefox_evidence for diagnostics') from firefox_error
    if parsed['raw_rows']==0 or not parsed['locations']:
        raise InvalidEvidence('Google Maps has no verified locations; cannot claim lack of competition')
    # Resume sidecar is evidence of upstream query checkpointing, not proof all local businesses exist.
    sidecar=Path(str(output)+'.resume.json')
    parsed.update({'source_url':'https://www.google.com/maps/','plan':spec,
                   'raw_sha256':sha256(output),'sidecar_present':sidecar.is_file(),
                   'source_file':str(output),'manual_audit_needed':True,'collector_used':used,'native_issue':native_issue})
    write_json(normalized,parsed)
    return parsed
