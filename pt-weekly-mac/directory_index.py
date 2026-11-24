"""Targeted index-directory discovery. No direct automated PT requests."""
import argparse,csv,datetime as dt,hashlib,json,re,time
from pathlib import Path
from urllib.parse import urlsplit,urlencode
from keyless_probe import exa,freeserp,Unavailable
ROOT=Path(__file__).resolve().parent
def url(fsa):return "https://www.psychologytoday.com/ca/therapists/"+fsa.lower()
def exact_url(value,fsa):
    try:u=urlsplit(value)
    except ValueError:return False
    return u.scheme=="https" and u.hostname in ("www.psychologytoday.com","psychologytoday.com") and u.path.rstrip("/").lower()=="/ca/therapists/"+fsa.lower() and not u.query
def extract_count(text,fsa):
    m=re.search(r"Number of Counsellors in\s+"+re.escape(fsa)+r"\s*(?:[:#*]\s*)*(<\s*\d+|\d[\d,]*\+?)(?![\d%])",text,re.I)
    return re.sub(r"[\s,]","",m.group(1)) if m else None
def extract(source,data,fsa):
    rows=[]
    if source=="freeserp":
        for x in data.get("results",[]):
            if isinstance(x,dict):
                rows.append((x.get("url","")," ".join(str(x.get(k) or "") for k in ("title","snippet","text","content")),x.get("crawled_at") or (x.get("source") or {}).get("captured_at") if isinstance(x.get("source") or {},dict) else None))
    elif source=="exa":
        for block in data.get("content",[]):
            if not isinstance(block,dict):continue
            raw=block.get("text","")
            for part in re.split(r"(?im)(?=^\s*(?:\d+\.\s*)?Title:\s*)",raw):
                matches=re.findall(r"(?im)^\s*URL:\s*(https?://[^\s]+)",part)
                if len(matches)==1:rows.append((matches[0],part,None))
    result=[]
    for u,t,age in rows:
        if exact_url(u,fsa):
            count=extract_count(t,fsa)
            if count:result.append((count,age))
    return result
def review_links(fsa):
    q=f'site:psychologytoday.com/ca/therapists/{fsa.lower()} "Number of Counsellors in {fsa}"'
    return {k:b+"?"+urlencode(dict(opts,q=q)) for k,b,opts in [
        ("google","https://www.google.ca/search",{"gl":"ca","hl":"en"}),
        ("bing","https://www.bing.com/search",{"cc":"ca"}),
        ("duckduckgo","https://duckduckgo.com/",{"kl":"ca-en"}),
        ("brave","https://search.brave.com/search",{"country":"ca"})]}
def proxy(count,pop):
    if re.fullmatch(r"<\d+",count):return (int(count[1:])-1)*10000/pop,"upper"
    if re.fullmatch(r"\d+\+",count):return int(count[:-1])*10000/pop,"lower"
    if re.fullmatch(r"\d+",count):return int(count)*10000/pop,"displayed"
    raise ValueError("Invalid displayed count")
def run(out,baseline=ROOT/"candidates.csv",seed=ROOT/"directory_snapshot.csv",providers=None,delay=time.sleep):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with Path(baseline).open() as f:areas=list(csv.DictReader(f))
    with Path(seed).open() as f:historical={r["fsa"]:r for r in csv.DictReader(f)}
    if len(areas)!=60 or len({r["fsa"] for r in areas})!=60 or set(historical)!={r["fsa"] for r in areas}:raise ValueError("Candidate/snapshot mismatch")
    providers=providers if providers is not None else [("exa",exa),("freeserp",freeserp)]
    rows=[];obs=[];stopped={}
    def save():
        p=out/"directory-index-evidence.json"
        tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(obs,indent=2));tmp.replace(p)
    for area in areas:
        fsa=area["fsa"];pop=int(area["census_population_2021"]);hits=[]
        query=f'{url(fsa)} "Number of Counsellors in {fsa}"'
        for name,fn in providers:
            rec={"fsa":fsa,"source":name,"query":query,"observed_at":dt.datetime.now(dt.timezone.utc).isoformat()}
            if name in stopped:rec.update(status="source_stopped",reason=stopped[name])
            else:
                try:
                    data=fn(query);counts=extract(name,data,fsa)
                    rec.update(status="indexed_directory_statistic" if counts else "no_matching_statistic",counts=counts,response_hash=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest())
                    hits.extend((name,c,a) for c,a in counts)
                except Exception as e:
                    rec.update(status="unavailable",reason=str(e)[:200])
                    if isinstance(e,Unavailable) and any(x in str(e).lower() for x in ("429","403","401","402","rate limit")):stopped[name]=str(e)
                delay(1)
            obs.append(rec);save()
        distinct={c for _,c,_ in hits}
        count=next(iter(distinct)) if len(distinct)==1 else historical[fsa]["displayed_count"]
        status="indexed_statistic_retrieved" if len(distinct)==1 else "conflicting_index_statistics_historical_fallback" if distinct else "historical_snapshot_only"
        score,bound=proxy(count,pop)
        rows.append(dict(fsa=fsa,population_2021=pop,directory_url=url(fsa),displayed_count=count,count_status=status,
            historical_displayed_count=historical[fsa]["displayed_count"],historical_capture_age=historical[fsa]["index_capture_age"],historical_review_date=historical[fsa]["review_date"],
            retrieved_index_statistics="; ".join(f"{n}:{c}:{a or 'capture date unknown'}" for n,c,a in hits),screening_proxy_per_10000=round(score,4),bound=bound,exact_current_count_verified=False,**review_links(fsa)))
    rows.sort(key=lambda r:r["screening_proxy_per_10000"])
    for i,r in enumerate(rows,1):r["screening_order"]=i
    with (out/"directory-screening.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return rows
def main():
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True);a=p.parse_args();rows=run(a.out)
    print(json.dumps({"areas":len(rows),"retrieved_index_statistics":sum(r["count_status"]=="indexed_statistic_retrieved" for r in rows),"exact_current_counts":0,"screening_only":True}))
    return 0 # Survey executed; coverage is assessed independently from process success
if __name__=="__main__":raise SystemExit(main())
