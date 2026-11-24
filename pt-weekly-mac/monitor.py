#!/usr/bin/env python3
"""Local weekly PT visibility monitor. No browser, no proxy rotation, no hidden billing."""
import argparse,csv,datetime as dt,fcntl,getpass,hashlib,json,os,re,sys,tempfile,time
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,urlencode,parse_qs
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
BASE="https://www.psychologytoday.com"
TZ=ZoneInfo("America/Toronto")
SOURCES=("brave","tavily","pt")
class SourceError(Exception): pass
class HaltSource(SourceError): pass
def now(): return dt.datetime.now(TZ)
def week(d): return (d-dt.timedelta(days=d.weekday())).isoformat()
def atomic(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,delete=False,encoding="utf8") as f:
        os.chmod(f.name,0o600); json.dump(obj,f,indent=2); tmp=f.name
    os.replace(tmp,path)
def load(path,default):
    return json.loads(path.read_text()) if path.exists() else default
def profile_id(url):
    u=urlsplit(url)
    if u.scheme!="https" or u.hostname not in ("www.psychologytoday.com","psychologytoday.com"): return None
    m=re.fullmatch(r"/ca/therapists/[^/]+/(\d{4,12})/?",u.path,re.I)
    return m.group(1) if m else None
def ids(urls): return sorted({p for u in urls if isinstance(u,str) and (p:=profile_id(u))})
class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.urls=[];self.words=[];self.ignored=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"): self.ignored+=1
        if tag=="a" and not self.ignored:
            a=dict(attrs)
            if a.get("href"): self.urls.append(a["href"])
    def handle_endtag(self,tag):
        if tag in ("script","style") and self.ignored:self.ignored-=1
    def handle_data(self,data):
        if not self.ignored:self.words.append(data)
def parse_pt(html,fsa,url):
    p=Links();p.feed(html);txt=" ".join(" ".join(p.words).split())
    if any(x in txt[:2500].lower() for x in ("verify you are human","access denied","just a moment","captcha","request blocked","unusual traffic")): raise HaltSource("PT verification or access restriction")
    if fsa.lower() not in txt[:6000].lower():raise SourceError("PT directory postal code not verified")
    links=[urljoin(url,u) for u in p.urls]; pageids=ids(links)
    match=re.search(r"Number of (?:Counsellors|Therapists) in\s+"+fsa+r"\s+([\d,]+)(\+?)",txt,re.I)
    total=int(match[1].replace(",","")) if match else None
    rounded=bool(match and match[2])
    pages=set()
    for link in links:
        u=urlsplit(link)
        if u.hostname not in ("www.psychologytoday.com","psychologytoday.com") or u.path.rstrip("/").lower()!="/ca/therapists/"+fsa.lower(): continue
        v=parse_qs(u.query).get("page",[])
        if len(v)==1 and v[0].isdigit():pages.add(int(v[0]))
    if not pageids and not (total==0 and not rounded):raise SourceError("No recognized PT profiles and no explicit zero")
    return pageids,pages,total,rounded
def http(url,headers=None,payload=None):
    h={"User-Agent":"LocalWeeklyCompetitionMonitor/1.0","Accept":"application/json" if "api." in url else "text/html","Cache-Control":"no-cache"}
    h.update(headers or {})
    try:
        with urlopen(Request(url,headers=h,data=payload),timeout=35) as r:
            raw=r.read(8_000_001)
            if len(raw)>8_000_000:raise SourceError("Response size limit")
            return raw.decode("utf8"),r.geturl()
    except HTTPError as e:
        if e.code in (401,402,403,429):raise HaltSource("HTTP "+str(e.code)+"; source stopped for this run") from None
        raise SourceError("HTTP "+str(e.code)) from None
def web_queries(fsa):
    return [f'site:psychologytoday.com/ca/therapists/ "{fsa}" therapist Ontario',
            f'site:psychologytoday.com/ca/therapists/ "{fsa}" ("online" OR "serves area" OR "location") Ontario']
def search(source,fsa,variant,key,fetch=http):
    q=web_queries(fsa)[variant]
    if source=="brave":
        url="https://api.search.brave.com/res/v1/web/search?"+urlencode(dict(q=q,country="CA",search_lang="en",count=20))
        h={"X-Subscription-Token":key,"X-Loc-Country":"CA","X-Loc-State":"ON"}
        if variant==1:h["X-Loc-Postal-Code"]=fsa
        raw,_=fetch(url,h)
        doc=json.loads(raw)
        if not isinstance(doc.get("web"),dict) or not isinstance(doc["web"].get("results"),list):raise SourceError("Unrecognized Brave response")
        rows=doc["web"]["results"]
        location=doc.get("query",{}).get("postal_code")
    else:
        req=dict(query=q,search_depth="basic",max_results=20,include_answer=False,include_raw_content=False,auto_parameters=False,country="canada")
        raw,_=fetch("https://api.tavily.com/search",{"Authorization":"Bearer "+key,"Content-Type":"application/json"},json.dumps(req).encode())
        doc=json.loads(raw);rows=doc.get("results");location=None
        if not isinstance(rows,list):raise SourceError("Unrecognized Tavily response")
    if any(not isinstance(x,dict) or not isinstance(x.get("url"),str) for x in rows):raise SourceError("Invalid search results")
    return {"ids":ids([x["url"] for x in rows]),"result_count":len(rows),"query":q,"location_requested":fsa if source=="brave" and variant==1 else "Canada","location_returned":location,"status":"indexed_discovery","sha256":hashlib.sha256(raw.encode()).hexdigest()}
def direct(fsa,fetch=http,delay=time.sleep,max_pages=100):
    found=set();seen=set();totals=set();proof=[];index=1;complete=False;reason="page cap"
    while index<=max_pages:
        url=BASE+"/ca/therapists/"+fsa.lower()+("?page="+str(index) if index>1 else "")
        raw,final=fetch(url)
        u=urlsplit(final)
        if u.hostname not in ("psychologytoday.com","www.psychologytoday.com") or u.path.rstrip("/").lower()!="/ca/therapists/"+fsa.lower():raise SourceError("PT redirected outside requested postal area")
        returned=parse_qs(u.query).get("page",["1"])[0]
        if returned!=str(index):raise SourceError("PT redirected to different page")
        pageids,pages,total,rounded=parse_pt(raw,fsa,final)
        digest=hashlib.sha256(raw.encode()).hexdigest()
        if digest in seen or (index>1 and not (set(pageids)-found)):
            reason="repeated page or no new IDs";break
        seen.add(digest);found.update(pageids)
        proof.append({"page":index,"hash":digest,"ids":pageids,"url":final})
        if total is not None:totals.add((total,rounded))
        if len(totals)>1:reason="directory totals changed";break
        if index+1 not in pages:
            if any(n>index+1 for n in pages):reason="pagination gap";break
            complete=True;reason="terminal page observed";break
        index+=1;delay(3)
    exact=complete and len(totals)==1 and (len(found),False) in totals
    return {"ids":sorted(found),"status":"visible_pages_checked" if exact else "partial_visible_observation","pages":proof,"reason":reason,"directory_totals":[list(x) for x in sorted(totals)],"exact_active_advertiser_count":False}
def baseline(path):
    with path.open(newline="",encoding="utf8") as f:rows=list(csv.DictReader(f))
    if len(rows)!=60 or len({r["fsa"] for r in rows})!=60:raise ValueError("Expected the saved 60 unique FSAs")
    for r in rows:
        if not re.fullmatch(r"[KLMNP]\d[A-Z]",r["fsa"]) or int(r["census_population_2021"])<=0:raise ValueError("Invalid baseline")
    return rows
def report(rows,records,out,period):
    result=[]
    for r in rows:
        f=r["fsa"];pop=int(r["census_population_2021"])
        matches=[x for x in records.values() if x.get("fsa")==f and x.get("week")==period]
        pt=[x for x in matches if x["source"]=="pt" and x.get("status") in ("visible_pages_checked","partial_visible_observation")]
        direct_ids=set().union(*(set(x["ids"]) for x in pt))
        indexes={s:set().union(*(set(x.get("ids",[])) for x in matches if x["source"]==s and x.get("status")=="indexed_discovery")) for s in SOURCES[:2]}
        discovery=set().union(*indexes.values())
        complete=[x for x in pt if x["status"]=="visible_pages_checked"]
        counts=[len(x["ids"]) for x in pt]
        count=len(direct_ids) if pt else None
        result.append(dict(fsa=f,population_2021=pop,pt_visible_unique=count,pt_observation_days=len({x["day"] for x in pt}),pt_terminal_count_agreements=len(complete),pt_daily_min=min(counts) if counts else None,pt_daily_max=max(counts) if counts else None,brave_discovered=len(indexes["brave"]) if any(x["source"]=="brave" and x.get("status")=="indexed_discovery" for x in matches) else None,tavily_discovered=len(indexes["tavily"]) if any(x["source"]=="tavily" and x.get("status")=="indexed_discovery" for x in matches) else None,index_only_unconfirmed=len(discovery-direct_ids),residents_per_visible_profile=round(pop/count,2) if count else None,visible_per_10k=round(count/pop*10000,3) if count is not None else None,status="observed_only" if complete else "incomplete_or_unavailable",exact_active_advertiser_count="unknown"))
    result.sort(key=lambda r:(r["status"]!="observed_only",r["pt_visible_unique"] is None,r["pt_visible_unique"] if r["pt_visible_unique"] is not None else 0,r["fsa"]))
    out.mkdir(parents=True,exist_ok=True)
    for name,items in [("by-visible-count.csv",result),("by-visible-per-10k.csv",sorted(result,key=lambda r:(r["status"]!="observed_only",r["visible_per_10k"] is None,r["visible_per_10k"] if r["visible_per_10k"] is not None else 0,r["fsa"])))]:
        target=out/name
        with tempfile.NamedTemporaryFile(mode="w",newline="",dir=out,delete=False,encoding="utf8") as f:
            w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(items);tmp=f.name
        os.replace(tmp,target)
    atomic(out/"coverage.json",{"week_start":period,"candidate_count":len(rows),"areas_with_terminal_count_agreement":sum(r["status"]=="observed_only" for r in result),"areas_with_two_or_more_direct_days":sum(r["pt_observation_days"]>=2 for r in result),"exact_ranking_certified":False,"records":len(records)})
    return result
def run(rows,config,home,stamp=None,fetch=http,delay=time.sleep):
    stamp=stamp or now();day=stamp.date().isoformat();period=week(stamp.date());out=home/period
    path=out/"observations.json";records=load(path,{})
    usagepath=home/"api-usage.json";usage=load(usagepath,{})
    stopped=set()
    for source in SOURCES:
        key=config.get(source+"_key","")
        enabled=bool(key) if source!="pt" else bool(config.get("pt_permission_reference"))
        if not enabled:print(source+": not configured; skipped");continue
        for r in rows:
            f=r["fsa"]
            for variant in range(1 if source=="pt" else 2):
                ident=f"{day}:{source}:{f}:{variant}"
                if ident in records and records[ident].get("status") in ("indexed_discovery","visible_pages_checked","partial_visible_observation"):continue
                if source in stopped:break
                if source!="pt":
                    month=day[:7]+":"+source
                    cap=min(600,max(0,int(config.get(source+"_monthly_cap",600))))
                    if usage.get(month,0)>=cap:stopped.add(source);print(source+": local monthly request limit reached");break
                    usage[month]=usage.get(month,0)+1;atomic(usagepath,usage)
                print(source,f,variant+1,flush=True)
                try:
                    result=direct(f,fetch,delay) if source=="pt" else search(source,f,variant,key,fetch)
                except HaltSource as e:
                    stopped.add(source);result={"status":"source_halted","error":str(e)}
                except (SourceError,OSError,ValueError) as e:
                    result={"status":"failed","error":type(e).__name__}
                result.update(fsa=f,source=source,day=day,week=period,observed_at=stamp.isoformat(),finished_at=now().isoformat(),variant=variant)
                records[ident]=result;atomic(path,records);delay(3 if source=="pt" else 1)
            if source in stopped:break
    report(rows,records,out,period)
    return out
def configure(path):
    c=load(path,{})
    for s in SOURCES[:2]:
        print(s+" API key (blank keeps existing / skips). Use a free or hard-capped provider account.")
        key=getpass.getpass()
        if key:c[s+"_key"]=key
    print("PT written permission reference (blank keeps existing / skips). Do not enter anything without actual permission.")
    ref=input().strip()
    if ref:c["pt_permission_reference"]=ref
    atomic(path,c);return c
def main():
    p=argparse.ArgumentParser();p.add_argument("--configure",action="store_true");p.add_argument("--home",type=Path,default=Path.home()/"Library/Application Support/PT Weekly Competition");p.add_argument("--baseline",type=Path,default=ROOT/"candidates.csv");a=p.parse_args()
    a.home.mkdir(parents=True,exist_ok=True);os.chmod(a.home,0o700)
    with (a.home/"run.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print("Another scan is running.");return 2
        configpath=a.home/"config.json"
        c=configure(configpath) if a.configure or not configpath.exists() else load(configpath,{})
        rows=baseline(a.baseline)
        if not any(c.get(s+"_key") for s in SOURCES[:2]) and not c.get("pt_permission_reference"):
            print("No authorized sources configured. No live results collected. Run Configure.command.");return 2
        out=run(rows,c,a.home);summary=load(out/"coverage.json",{})
        print("Reports:",out);print(json.dumps(summary,indent=2))
        if summary.get("areas_with_terminal_count_agreement")!=60:return 3
    return 0
if __name__=="__main__":sys.exit(main())
