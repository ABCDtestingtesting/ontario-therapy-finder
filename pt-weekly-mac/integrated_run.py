#!/usr/bin/env python3
"""Combined local launcher. Live direct directory ranking, independently audited search evidence."""
import csv,json,os,sys,time,subprocess,signal,fcntl,datetime as dt,shutil,secrets,re
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import urlopen
from release_gate import audit
from metasearch_audit import ENGINES
ROOT=Path(__file__).resolve().parent
TZ=ZoneInfo("America/Toronto")
def write(path,body):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body,indent=2));tmp.replace(path)
def read(path,default):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default
def browser():
    py=ROOT/".venv/bin/python"
    if not py.exists():subprocess.run([sys.executable,"-m","venv",str(ROOT/".venv")],check=True)
    if subprocess.run([str(py),"-c","import playwright"]).returncode:
        subprocess.run([str(py),"-m","pip","install","playwright"],check=True)
    probe="from pathlib import Path;from playwright.sync_api import sync_playwright\nwith sync_playwright() as p: assert Path(p.firefox.executable_path).exists()"
    if subprocess.run([str(py),"-c",probe]).returncode:subprocess.run([str(py),"-m","playwright","install","firefox"],check=True)
    return subprocess.call([str(py),"-u",str(ROOT/"decision_live_check.py")])
def index():
    from keyless_probe import survey
    return survey(output=Path("index-evidence.json"),baseline=ROOT/"candidates.csv",resume=False)
def named():
    from metasearch_audit import run
    base="http://127.0.0.1:8888";folder=Path("named-engines");folder.mkdir(exist_ok=True)
    def ready():
        try:
            with urlopen(base+"/healthz",timeout=2) as r:return r.status==200
        except Exception:return False
    owned=None
    try:
        if not ready() and shutil.which("docker"):
            try:
                if subprocess.run(["docker","info"],capture_output=True,timeout=10).returncode==0:
                    owned="pt-weekly-"+secrets.token_hex(5)
                    (folder/"owned-container.txt").write_text(owned)
                    config=folder/"settings.yml"
                    config.write_text('use_default_settings: true\nserver:\n  secret_key: "'+secrets.token_hex(24)+'"\n  limiter: false\n  image_proxy: false\nsearch:\n  formats: [html, json]\n')
                    subprocess.run(["docker","run","-d","--rm","--name",owned,"-p","127.0.0.1:8888:8080","-v",str(config.resolve())+":/etc/searxng/settings.yml:ro","docker.io/searxng/searxng:latest"],check=True,timeout=180)
                    for _ in range(30):
                        if ready():break
                        time.sleep(2)
            except (OSError,subprocess.SubprocessError):pass
        if not ready():
            write(folder/"engine-coverage.json",{"all_engines_verified":False,"status":"No local metasearch server","coverage":{}})
            return 3
        report=run(base,folder)
        return 0 if report["all_engines_verified"] else 3
    finally:
        if owned:
            try:subprocess.run(["docker","stop","-t","1",owned],capture_output=True,timeout=10)
            except (OSError,subprocess.SubprocessError):pass
def finalize(out,elapsed,workers):
    with (ROOT/"candidates.csv").open() as f:areas=list(csv.DictReader(f))
    assert len(areas)==len({a["fsa"] for a in areas})==60
    direct=read(out/"decision-live-evidence/status.json",{})
    pages=read(out/"decision-live-evidence/pages.json",{})
    indexed=read(out/"index-evidence.json",{})
    named=read(out/"named-engines/engine-coverage.json",{})
    namedrows=read(out/"named-engines/engine-evidence.json",[])
    index_audit=audit(indexed,areas)
    rows=[]
    for a in areas:
        f=a["fsa"];pop=int(a["census_population_2021"]);s=pages.get(f,{})
        pp=s.get("pages",[]);ids=set()
        valid=bool(pp) and s.get("status")=="complete"
        for i,p in enumerate(pp,1):
            values=p.get("ids",[])
            if not isinstance(values,list) or not values or any(not isinstance(x,str) or not re.fullmatch(r"\d{4,12}",x) for x in values):
                valid=False;continue
            if p.get("page")!=i or p.get("next_page")!=(i+1 if i<len(pp) else None):valid=False
            if not set(values)-ids:valid=False
            ids.update(values)
        if pp:
            label=pp[0].get("directory_label","")
            if any(p.get("directory_label")!=label for p in pp):valid=False
            if not re.fullmatch(r"(?:<\d+|\d+\+?)",label):valid=False
            elif not label.startswith("<") and len(ids)<int(label.rstrip("+")):valid=False
        else:label=""
        scope=set()
        for x in indexed.get("observations",[]):
            if x.get("fsa")==f and x.get("status")=="indexed_leads_only":scope.update(x.get("postal_text_ids",[]))
        engine_scope=set()
        relevant_engines=set()
        for x in namedrows:
            if x.get("fsa")==f and x.get("status")=="relevant_results" and x.get("engine") in ENGINES:
                engine_scope.update(x.get("postal_profile_ids",[]));relevant_engines.add(x["engine"])
        scope.update(engine_scope)
        rows.append(dict(fsa=f,population=pop,observed_direct_profiles=len(ids),direct_pages=len(pp),direct_status="complete" if valid else "incomplete",directory_label=label,
            observed_direct_profiles_per_10000=round(len(ids)*10000/pop,6) if valid else None,
            indexed_postal_profile_leads=len(scope),index_leads_also_seen_directly=len(scope&ids),index_leads_not_seen_directly=len(scope-ids),named_engines_with_relevant_results=";".join(sorted(relevant_engines))))
    rows.sort(key=lambda r:(r["direct_status"]!="complete",r["observed_direct_profiles_per_10000"] if r["observed_direct_profiles_per_10000"] is not None else float("inf"),r["fsa"]))
    full=sum(r["direct_status"]=="complete" for r in rows)==60 and direct.get("full_live_verification") is True and workers.get("browser")==0
    for i,r in enumerate(rows,1):
        r["observed_direct_rank"]=i if full else None
    with (out/"weekly-ranking.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["observed_direct_rank"]+[k for k in rows[0] if k!="observed_direct_rank"]);w.writeheader();w.writerows(rows)
    all_named=bool(workers.get("named")==0 and named.get("all_engines_verified") and all(named.get("coverage",{}).get(e,{}).get("areas_with_relevant_results")==60 for e in ENGINES))
    all_index=bool(workers.get("index")==0 and index_audit["index_survey_verified"] and index_audit["areas_with_any_leads"]==60)
    status={"areas":60,"direct_areas_completed":sum(r["direct_status"]=="complete" for r in rows),"direct_pages":sum(r["direct_pages"] for r in rows),"direct_page_chains_verified":full,"index_search_verified":all_index,"index_audit":index_audit,"named_search_verified":all_named,"named_search_coverage":named,"workers":workers,"elapsed_seconds":round(elapsed,3),"runtime_target_seconds":3600,"completed_within_target":full and all_index and all_named and elapsed<=3600,"ranking_scope":"Observed visible PT directory listings across 60 candidate FSAs; search-index leads are separate cross-checks."}
    write(out/"run-status.json",status)
    return status
def main():
    if len(sys.argv)==3 and sys.argv[1]=="--worker":return {"browser":browser,"index":index,"named":named}[sys.argv[2]]()
    start=time.monotonic()
    home=Path(os.environ.get("PT_RESULTS_HOME",str(Path.home()/"Desktop"/"PT Direct Results"))).resolve()
    home.mkdir(parents=True,exist_ok=True)
    with (home/"scan.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print("Scan already running.");return 3
        out=home/dt.datetime.now(TZ).strftime("%Y-%m-%d-%H%M%S-%f");out.mkdir()
        print("Results:",out,flush=True)
        children={};logs=[];status={}
        try:
            for name in ("browser","index","named"):
                log=(out/(name+".log")).open("w");logs.append(log)
                children[name]=subprocess.Popen([sys.executable,"-u",str(ROOT/"integrated_run.py"),"--worker",name],cwd=out,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            while len(status)<len(children) and time.monotonic()-start<3560:
                for n,p in children.items():
                    if n not in status and p.poll() is not None:status[n]=p.returncode;print(n,status[n],flush=True)
                if len(status)<len(children):time.sleep(.25)
        finally:
            for n,p in children.items():
                if p.poll() is None:
                    status[n]="deadline_or_interruption"
                    try:os.killpg(p.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
            for n,p in children.items():
                try:p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    p.wait(timeout=2)
            for log in logs:log.close()
            owner=out/"named-engines/owned-container.txt"
            if owner.exists() and shutil.which("docker"):
                n=owner.read_text().strip()
                if re.fullmatch(r"pt-weekly-[a-f0-9]{10}",n):
                    try:subprocess.run(["docker","stop","-t","1",n],capture_output=True,timeout=8)
                    except (OSError,subprocess.SubprocessError):pass
        report=finalize(out,time.monotonic()-start,status)
        report["elapsed_seconds"]=round(time.monotonic()-start,3)
        report["completed_within_target"]=report["completed_within_target"] and report["elapsed_seconds"]<=3600
        write(out/"run-status.json",report);print(json.dumps(report,indent=2),flush=True)
        return 0 if report["completed_within_target"] else 3
if __name__=="__main__":raise SystemExit(main())
