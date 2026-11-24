#!/usr/bin/env python3
"""Local, no-account, index visibility survey. No direct directory scraping."""
import argparse,csv,datetime as dt,fcntl,json,os,tempfile
from pathlib import Path
from zoneinfo import ZoneInfo
from keyless_probe import survey
from release_gate import audit
ROOT=Path(__file__).resolve().parent
TZ=ZoneInfo("America/Toronto")
def atomic(path,doc):
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf8",dir=path.parent,delete=False) as f:
        os.chmod(f.name,0o600);json.dump(doc,f,indent=2);name=f.name
    os.replace(name,path)
def write_approximation(out,result,verified_days,snapshot=ROOT/"directory_snapshot.csv"):
    # This is a reproducible competition proxy, not an advertiser census.
    # An observed same-week postal-text match is required for each area.
    from directory_index import proxy
    with snapshot.open(newline="",encoding="utf8") as f:
        old={x["fsa"]:x for x in csv.DictReader(f)}
    if len(result)!=60 or len({x["fsa"] for x in result})!=60 or set(old)!={x["fsa"] for x in result}:
        raise ValueError("Expected exactly the same 60 candidate areas")
    items=[]
    for x in result:
        f=x["fsa"];pop=x["population_2021"];n=x["unique_index_leads_with_postal_text"]
        count=old[f]["displayed_count"]
        historic,bound=proxy(count,pop)
        items.append(dict(fsa=f,population_2021=pop,postal_text_index_leads=n,
            postal_text_leads_per_10000=round(n*10000/pop,4) if n is not None else None,
            historical_directory_count=count,historical_directory_bound=bound,
            historical_directory_proxy_per_10000=round(historic,4),
            historical_index_capture_age=old[f]["index_capture_age"],
            verified_search_days=";".join(verified_days),directory_url=x["directory_url"],
            fresh_search_evidence=bool(verified_days and n is not None and n>0)))
    # Rank both signals separately, then average ranks. Missing search evidence
    # is never interpreted as zero competition or promoted above observed areas.
    def ranks(key,subset):
        vals=sorted(x[key] for x in subset)
        return {x["fsa"]:1+(vals.index(x[key])+len(vals)-1-vals[::-1].index(x[key]))/2 for x in subset}
    observed=[x for x in items if x["fresh_search_evidence"]]
    a=ranks("postal_text_leads_per_10000",observed);b=ranks("historical_directory_proxy_per_10000",observed)
    for x in items:
        f=x["fsa"]
        x["combined_rank_score"]=round((a[f]+b[f])/2,2) if f in a else None
        x["exact_current_directory_count_verified"]=False
        x["evidence_status"]="same_week_index_leads_plus_historical_count" if f in a else "historical_count_only"
    items.sort(key=lambda x:(x["combined_rank_score"] is None,x["combined_rank_score"] if x["combined_rank_score"] is not None else x["historical_directory_proxy_per_10000"],x["historical_directory_proxy_per_10000"],x["fsa"]))
    for i,x in enumerate(items,1):x["approximate_rank"]=i
    with (out/"weekly-top60-approximation.csv").open("w",newline="",encoding="utf8") as f:
        wr=csv.DictWriter(f,fieldnames=["approximate_rank"]+[k for k in items[0] if k!="approximate_rank"]);wr.writeheader();wr.writerows(items)
    return len(observed)
def weekly(home,baseline,day,collector=survey):
    day=day if isinstance(day,dt.date) else dt.date.fromisoformat(day)
    period=day-dt.timedelta(days=day.weekday())
    out=home/period.isoformat();out.mkdir(parents=True,exist_ok=True)
    daily=out/(day.isoformat()+".json")
    with baseline.open(newline="",encoding="utf8") as f: rows=list(csv.DictReader(f))
    code=collector(output=daily,baseline=baseline,resume=True)
    daily_data=json.loads(daily.read_text());current=audit(daily_data,rows)
    if daily_data.get("survey_day")!=day.isoformat():
        current["index_survey_verified"]=False;current["problems"].append("Daily file date does not match survey date")
    verified_days=[];day_data=[]
    for p in sorted(out.glob("????-??-??.json")):
        date=dt.date.fromisoformat(p.stem)
        if not period<=date<=period+dt.timedelta(days=6) or date>day:continue
        d=json.loads(p.read_text());a=audit(d,rows)
        if d.get("survey_day")==p.stem and a["index_survey_verified"]:
            verified_days.append(p.stem);day_data.append((p.stem,d))
    result=[]
    for row in rows:
        f=row["fsa"];pop=int(row["census_population_2021"])
        sets={s:set() for s in ("exa","freeserp")}
        per_day=[];all_ids=set();postal_ids=set()
        for date,d in day_data:
            daily_ids=set()
            for x in d["observations"]:
                if x["fsa"]==f:
                    sets[x["source"]].update(x["ids"]);daily_ids.update(x["ids"]);postal_ids.update(x["postal_text_ids"])
            all_ids.update(daily_ids);per_day.append(len(daily_ids))
        result.append({"fsa":f,"population_2021":pop,"directory_url":"https://www.psychologytoday.com/ca/therapists/"+f.lower(),
          "unique_index_leads_with_postal_text":len(postal_ids) if verified_days else None,
          "postal_text_leads_per_10000_residents":round(len(postal_ids)*10000/pop,4) if verified_days else None,"verified_index_survey_days":len(verified_days),
          "exa_unique_index_leads":len(sets["exa"]) if verified_days else None,
          "freeserp_unique_index_leads":len(sets["freeserp"]) if verified_days else None,
          "union_index_leads":len(all_ids) if verified_days else None,
          "cross_index_shared_leads":len(sets["exa"]&sets["freeserp"]) if verified_days else None,
          "daily_index_leads_min":min(per_day) if per_day else None,
          "daily_index_leads_max":max(per_day) if per_day else None,
          "active_pt_competitors":None,"residents_per_confirmed_competitor":None,
          "status":"indexed_leads_only" if verified_days else "unavailable"})
    with tempfile.NamedTemporaryFile(mode="w",newline="",encoding="utf8",dir=out,delete=False) as f:
        os.chmod(f.name,0o600)
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result);name=f.name
    os.replace(name,out/"weekly-index-visibility.csv")
    covered=write_approximation(out,result,verified_days)
    status={"approximation_areas_with_same_week_search_evidence":covered,"approximation_complete":covered==60,"week_start":period.isoformat(),"verified_days":verified_days,"three_distinct_survey_days":len(verified_days)>=3,
      "current_audit":current,"exact_competitor_ranking_ready":False,"source_scope":"Third-party indexed profile leads; not active PT advertisers.",
      "source_options":{"exa":"anonymous indexed search","freeserp":"anonymous indexed search","google":"no eligible public search API",
      "bing":"search API retired","brave":"key and billing details required","duckduckgo":"no verified full-result anonymous API",
      "direct_pt":"not enabled; written authorization needed"}}
    atomic(out/"coverage.json",status)
    print(json.dumps(status,indent=2));print("Reports:",out,flush=True)
    return 0 if code==0 and current["index_survey_verified"] and covered==60 else 3
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--home",type=Path,default=Path.home()/"Library/Application Support/PT Weekly Index Survey")
    p.add_argument("--baseline",type=Path,default=ROOT/"candidates.csv")
    a=p.parse_args();a.home.mkdir(parents=True,exist_ok=True);os.chmod(a.home,0o700)
    with (a.home/"run.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print("A survey is already running.");return 2
        return weekly(a.home,a.baseline,dt.datetime.now(TZ).date())
if __name__=="__main__":raise SystemExit(main())
