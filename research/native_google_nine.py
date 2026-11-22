"""Google-only independent gridded source for unresolved top-60 contenders.

Uses the published gosom Google Maps collector in a Docker container. This
probe is bounded, saves raw evidence, geolocates and filters 5-km radius, and
never converts a failed Google source into zero competitors.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from research.scan_all_maps import distance_km

TERMS = ("psychotherapist", "psychologist", "counselling therapy", "mental health clinic")
NINE = ("L4M","L1A","N7M","N1R","L4P","L9L","L0B","L0M","L7M")
ACCEPT = ("psychotherap", "psycholog", "counsel", "counsell", "mental health", "social work",
          "marriage", "family therap", "behavioral health", "behavioural health")
REJECT = ("physiotherap", "physical therap", "chiropract", "massage", "animal shelter",
          "conservation area", "pharmacy", "real estate", "dog", "fitness", "pet", "naturopath")
RADIUS = 5.0


def coords(centre):
    lat, lon = centre
    dlat = 5.2 / 111.1
    dlon = 5.2 / (111.1 * math.cos(math.radians(lat)))
    return f'{lat-dlat:.6f},{lon-dlon:.6f},{lat+dlat:.6f},{lon+dlon:.6f}'


def category_ok(row):
    name=(row.get("title") or "").strip().casefold()
    category=(row.get("category") or "").strip().casefold()
    alltext = name + " " + category
    if any(word in category for word in ACCEPT):
        return True
    if any(word in alltext for word in REJECT):
        return False
    # If category is non-clinical or missing, a name alone is insufficient.
    return bool(name and any(word in name for word in ACCEPT) and not category)


def parse_places(path,centre):
    places={}
    bad=[]
    total=outside=nonclinical=0
    with Path(path).open(newline="",encoding="utf-8-sig") as file:
        reader=csv.DictReader(file)
        required={"title","latitude","longitude","link"}
        if not required <= set(reader.fieldnames or []):
            raise RuntimeError("Google native CSV schema lacks title/lat/lon/link")
        for row in reader:
            total += 1
            try:
                lat,lon = float(row["latitude"]), float(row["longitude"])
            except (TypeError,ValueError):
                bad.append({"title": row.get("title"),"link":row.get("link")})
                continue
            if not (41 < lat < 57 and -96 < lon < -73):
                bad.append({"title": row.get("title"),"link":row.get("link")})
                continue
            if distance_km(centre,(lat,lon)) > RADIUS:
                outside += 1
                continue
            if not category_ok(row):
                nonclinical += 1
                continue
            key = ((row.get("place_id") or row.get("cid") or "").strip()
                   or (row.get("title") or "").casefold().strip()
                   + "|" + str(round(lat,5)) + "|" + str(round(lon,5)))
            places[key] = {
                "id": key, "name": row.get("title"), "lat": lat, "lon": lon,
                "category": row.get("category"), "address": row.get("address"),
                "google_maps_url": row.get("link"), "source": "Google Maps via gosom"
            }
    return {"valid_places":list(places.values()),"raw_rows":total,"outside_radius":outside,
            "not_clinical":nonclinical,"bad_coordinates":bad}


def run(fsa,first_pass,out, timeout=1800):
    folder=Path(out)/fsa
    folder.mkdir(parents=True,exist_ok=True)
    with open(first_pass,newline="") as fh:
        allrows=list(csv.DictReader(fh))
    if len(allrows)!=498 or len({r["fsa"] for r in allrows})!=498:
        raise RuntimeError("Expected complete 498-region baseline")
    match=[r for r in allrows if r["fsa"]==fsa]
    if len(match)!=1 or fsa not in NINE:
        raise RuntimeError("Unknown or unexpected FSA "+fsa)
    region=match[0]
    centre=(float(region["latitude"]),float(region["longitude"]))
    (folder/"queries.txt").write_text("\n".join(TERMS)+"\n")
    source=(folder/"native_google_raw.csv")
    bbox=coords(centre)
    container=os.environ.get("GOOGLE_DOCKER_IMAGE","gosom/google-maps-scraper:latest")
    output=folder.resolve()
    args=[
        "docker","run","--rm","--shm-size=1g",
        "-v",f"{output}:/out",container,
        "-input","/out/queries.txt","-results","/out/native_google_raw.csv",
        "-grid-bbox",bbox,"-grid-cell","2.1","-grid-strict",
        "-zoom","16","-depth","6","-c","3",
        "-exit-on-inactivity","12m"
    ]
    if source.exists() and source.stat().st_size>100:
        args.insert(args.index("-input"),"-resume")
    meta = {"fsa":fsa,"center":centre,"bbox":bbox,"radius_km":5,
            "terms":TERMS,"grid_cell_km":2.1,"collector_image":container,
            "collector_command":args,"started_at":datetime.now(timezone.utc).isoformat()}
    (folder/"run_plan.json").write_text(json.dumps(meta,indent=2))
    rc=None
    started=time.monotonic()
    with (folder/"collector.log").open("a") as log:
        try:
            p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
            rc=p.returncode
        except subprocess.TimeoutExpired:
            rc=124
    meta["duration_seconds"]=round(time.monotonic()-started,2)
    meta["process_returncode"]=rc
    meta["completed_at"]=datetime.now(timezone.utc).isoformat()
    status="source_failed"
    if source.is_file() and source.stat().st_size>50:
        try:
            observed=parse_places(source,centre)
            meta.update(observed)
            meta["unique_clinical_local_places"]=len(observed["valid_places"])
            meta["raw_csv_sha256"]=hashlib.sha256(source.read_bytes()).hexdigest()
            if rc==0 and not observed["bad_coordinates"]:
                status="grid_observed_complete" if observed["raw_rows"]>0 else "grid_empty_unconfirmed"
            elif rc!=0:
                status="partial_native"
            else:
                status="coordinates_incomplete"
        except Exception as exc:
            meta["parse_error"]=str(exc)
    else:
        meta["source_empty_or_missing"]=True
    meta["status"]=status
    (folder/"native_evidence.json").write_text(json.dumps(meta,indent=2))
    print("NATIVE_GOOGLE_FSA",json.dumps({
        "fsa":fsa,"status":status,"rc":rc,
        "raw_rows":meta.get("raw_rows"),"clinical_within_5km":meta.get("unique_clinical_local_places"),
        "outside":meta.get("outside_radius"),"nonclinical":meta.get("not_clinical"),
        "bad_coords":len(meta.get("bad_coordinates",[]))
    }),flush=True)
    return meta


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--fsa",choices=NINE,required=True)
    parser.add_argument("--first-pass",default="first-pass/google_all_ontario_498.csv")
    parser.add_argument("--out",default="native-google")
    parser.add_argument("--timeout",type=int,default=1800)
    args=parser.parse_args()
    run(args.fsa,args.first_pass,args.out,args.timeout)
