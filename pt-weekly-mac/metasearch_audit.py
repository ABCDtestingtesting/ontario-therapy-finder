"""Independent metasearch backend audit; never count empty results or silent fallback."""
import argparse,concurrent.futures,csv,datetime,json,time
from pathlib import Path
from urllib.parse import urlencode,urlsplit
from urllib.request import urlopen,Request
from keyless_probe import profile_id,mentions_fsa
from directory_index import exact_url,extract_count
ENGINES=("google","bing","duckduckgo","brave","startpage","yahoo","mojeek","yandex","qwant","ecosia")
ROOT=Path(__file__).resolve().parent
def parse(fsa,engine,obj):
    relevant=[];counts=[];ids=set()
    errors=[str(x[1]) for x in obj.get("unresponsive_engines",[]) if isinstance(x,list) and len(x)>1 and x[0]==engine]
    for item in obj.get("results",[]):
        # No silent attribution of another engine's response.
        if engine not in set(item.get("engines",[]))|{item.get("engine")}:continue
        u=item.get("url","");t=" ".join(str(item.get(k) or "") for k in ("title","content"))
        pid=profile_id(u);direct=exact_url(u,fsa)
        if not direct and not (pid and mentions_fsa(t,fsa)):continue
        relevant.append({"url":u,"title":item.get("title"),"engine":engine})
        if pid:ids.add(pid)
        if direct:
            c=extract_count(t,fsa)
            if c:counts.append(c)
    return dict(fsa=fsa,engine=engine,relevant_results=relevant,postal_profile_ids=sorted(ids),directory_counts=sorted(set(counts)),errors=errors,
        status="relevant_results" if relevant else "unavailable" if errors else "no_relevant_results")
def run(base,out,limit=None,delay=3):
    with (ROOT/"candidates.csv").open() as f:areas=[r["fsa"] for r in csv.DictReader(f)]
    if limit:areas=areas[:limit]
    results=[];stopped={}
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    def request(engine,fsa):
        q=f'site:psychologytoday.com/ca/therapists/ "{fsa}" Ontario therapists'
        params=dict(q=q,format="json",engines=engine,language="en-CA")
        req=Request(base.rstrip("/")+"/search?"+urlencode(params),headers={"Accept":"application/json","User-Agent":"PT-competition-survey/1.0"})
        try:
            with urlopen(req,timeout=30) as response:
                obj=json.load(response)
            row=parse(fsa,engine,obj)
        except Exception as e:
            row=dict(fsa=fsa,engine=engine,relevant_results=[],postal_profile_ids=[],directory_counts=[],errors=[str(e)[:250]],status="unavailable")
        row["query"]=q;row["observed_at"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
        return row
    for fsa in areas:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ENGINES)) as pool:
            tasks={e:pool.submit(request,e,fsa) for e in ENGINES if e not in stopped}
            for e in ENGINES:
                if e in tasks:
                    row=tasks[e].result()
                    reason=" ".join(row["errors"]).lower()
                    if any(x in reason for x in ("captcha","too many requests","rate limit","access denied","forbidden","suspended","429","403")):stopped[e]=reason
                else:row=dict(fsa=fsa,engine=e,status="stopped_due_to_restriction",errors=[stopped[e]],relevant_results=[],postal_profile_ids=[],directory_counts=[])
                results.append(row)
        (out/"engine-evidence.json").write_text(json.dumps(results,indent=2))
        time.sleep(delay)
    coverage={e:{"attempted":sum(x["engine"]==e and x["status"]!="stopped_due_to_restriction" for x in results),"areas_with_relevant_results":sum(x["engine"]==e and x["status"]=="relevant_results" for x in results),"areas_with_directory_counts":sum(x["engine"]==e and bool(x["directory_counts"]) for x in results),"restriction":stopped.get(e)} for e in ENGINES}
    report={"areas":len(areas),"coverage":coverage,"all_engines_verified":all(x["areas_with_relevant_results"]==len(areas) for x in coverage.values())}
    (out/"engine-coverage.json").write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    return report
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--base",default="http://127.0.0.1:8888");p.add_argument("--out",required=True);p.add_argument("--limit",type=int);a=p.parse_args();run(a.base,a.out,a.limit)
