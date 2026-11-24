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
def weekly(home,baseline,day,collector=survey):
    day=day if isinstance(day,dt.date) else dt.date.fromisoformat(day)
    period=day-dt.timedelta(days=day.weekday())
    out=home/period.isoformat();out.mkdir(parents=True,exist_ok=True)
    daily=out/(day.isoformat()+".json")
    with baseline.open(newline="",encoding="utf8") as f: rows=list(csv.DictReader(f))
    code=collector(output=daily,baseline=baseline,resume=True)
    current=audit(json.loads(daily.read_text()),rows)
    verified_days=[];day_data=[]
    for p in sorted(out.glob("????-??-??.json")):
        date=dt.date.fromisoformat(p.stem)
        if not period<=date<=period+dt.timedelta(days=6) or date>day:continue
        d=json.loads(p.read_text());a=audit(d,rows)
        if a["index_survey_verified"]:
            verified_days.append(p.stem);day_data.append((p.stem,d))
    result=[]
    for row in rows:
        f=row["fsa"];pop=int(row["census_population_2021"])
        sets={s:set() for s in ("exa","freeserp")}
        per_day=[];all_ids=set()
        for date,d in day_data:
            daily_ids=set()
            for x in d["observations"]:
                if x["fsa"]==f:
                    sets[x["source"]].update(x["ids"]);daily_ids.update(x["ids"])
            all_ids.update(daily_ids);per_day.append(len(daily_ids))
        result.append({"fsa":f,"population_2021":pop,"verified_index_survey_days":len(verified_days),
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
    status={"week_start":period.isoformat(),"verified_days":verified_days,"three_distinct_survey_days":len(verified_days)>=3,
      "current_audit":current,"exact_competitor_ranking_ready":False,"source_scope":"Third-party indexed profile leads; not active PT advertisers.",
      "source_options":{"exa":"anonymous indexed search","freeserp":"anonymous indexed search","google":"no eligible public search API",
      "bing":"search API retired","brave":"key and billing details required","duckduckgo":"no verified full-result anonymous API",
      "direct_pt":"not enabled; written authorization needed"}}
    atomic(out/"coverage.json",status)
    print(json.dumps(status,indent=2));print("Reports:",out,flush=True)
    return 0 if code==0 and current["index_survey_verified"] else 3
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
