#!/usr/bin/env python3
"""Fail-closed release gate for PT competition evidence; never treats index leads as confirmed listings."""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SOURCES=("freeserp","exa")
VARIANTS=(0,1)
RESPONSES={"indexed_leads_only","no_indexed_leads_not_zero_competitors"}
ROOT=Path(__file__).resolve().parent

def audit(data, candidates):
    expected={r["fsa"]:int(r["census_population_2021"]) for r in candidates}
    if len(candidates)!=60 or len(expected)!=60 or any(not re.fullmatch(r"[KLMNP]\d[A-Z]",f) or n<=0 for f,n in expected.items()):
        raise ValueError("Invalid 60-area candidate baseline")
    required={(f,s,v) for f in expected for s in SOURCES for v in VARIANTS}
    records=data.get("observations",[])
    counts=Counter()
    usable=set()
    ids_by_area=defaultdict(set)
    areas_by_id=defaultdict(set)
    problems=[]
    for row in records:
        key=(row.get("fsa"),row.get("source"),row.get("variant"))
        counts[key]+=1
        if key not in required:
            problems.append("unexpected observation key: "+repr(key));continue
        f,s,v=key
        if row.get("population_2021")!=expected[f] or not isinstance(row.get("query"),str) or ('"'+f+'"') not in row["query"]:
            problems.append("scope mismatch: "+repr(key));continue
        if row.get("status") not in RESPONSES:continue
        ids=row.get("ids")
        if not isinstance(ids,list) or any(not isinstance(i,str) or not re.fullmatch(r"\d{4,12}",i) for i in ids) or len(ids)!=len(set(ids)):
            problems.append("invalid or duplicate profile IDs: "+repr(key));continue
        if bool(ids)!=(row["status"]=="indexed_leads_only"):
            problems.append("inconsistent response status: "+repr(key));continue
        if not re.fullmatch(r"[a-f0-9]{64}",str(row.get("response_hash",""))):
            problems.append("missing response hash: "+repr(key));continue
        usable.add(key)
        ids_by_area[f].update(ids)
        for i in ids:areas_by_id[i].add(f)
    missing=required-set(counts)
    duplicates={k for k,n in counts.items() if n!=1}
    incomplete=required-usable
    if missing:problems.append(f"{len(missing)} missing observation keys")
    if duplicates:problems.append(f"{len(duplicates)} duplicate observation keys")
    if incomplete:problems.append(f"{len(incomplete)} missing or unusable index responses")
    if data.get("exact_active_advertiser_ranking_certified") is not False:
        problems.append("index artifact incorrectly asserts exact ranking")
    coverage_ok=not problems
    # Cross-area appearance is a diagnostic only: legitimate multi-location advertisers exist.
    shared={i:len(fs) for i,fs in areas_by_id.items() if len(fs)>1}
    return {"index_survey_verified":coverage_ok,"expected_observations":len(required),
            "usable_observations":len(usable),"areas_with_any_leads":sum(bool(ids_by_area[f]) for f in expected),
            "unique_index_profile_ids":len(areas_by_id),"ids_seen_in_multiple_areas":len(shared),
            "ids_seen_in_30_or_more_areas":sum(n>=30 for n in shared.values()),
            "maximum_areas_for_one_id":max((len(v) for v in areas_by_id.values()),default=0),
            "problems":problems,"release_ready":False,"exact_active_advertiser_ranking_certified":False,
            "blocking_conditions":["Third-party index results do not establish current Psychology Today listing-area eligibility or exhaustiveness.",
              "No verified direct directory coverage or authoritative active-profile export.",
              "The original provincewide lowest-60 individual-therapist ranking remains uncertified."]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("evidence",type=Path)
    p.add_argument("--baseline",type=Path,default=ROOT/"candidates.csv")
    p.add_argument("--output",type=Path)
    p.add_argument("--require-release",action="store_true",help="fail until the final deliverable is verified")
    a=p.parse_args()
    with a.baseline.open(newline="",encoding="utf8") as f: candidates=list(csv.DictReader(f))
    result=audit(json.loads(a.evidence.read_text()),candidates)
    body=json.dumps(result,indent=2)
    if a.output:a.output.write_text(body+"\n",encoding="utf8")
    print(body)
    return 0 if result["index_survey_verified"] and not a.require_release else 3

if __name__=="__main__":raise SystemExit(main())
