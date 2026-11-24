"""Evaluate officially documented Bing search RSS as a separate discovery source."""
import csv,json,urllib.request,urllib.error,xml.etree.ElementTree as ET,hashlib,time
from urllib.parse import urlencode
from pathlib import Path
from directory_index import extract, url
from keyless_probe import profile_id,Unavailable
ROOT=Path(__file__).resolve().parent
def parse_rss(body):
    if len(body)>2_000_000:raise Unavailable("Oversized feed")
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():raise Unavailable("Unexpected XML declaration")
    root=ET.fromstring(body)
    if root.tag!="rss" or root.find("channel") is None:raise Unavailable("Not an RSS search feed")
    rows=[]
    for item in root.findall("./channel/item"):
        link=item.findtext("link","")
        if not link:continue
        rows.append({"url":link,"title":item.findtext("title",""),"snippet":item.findtext("description","")})
    return {"results":rows}
def bing_rss(query):
    endpoint="https://www.bing.com/search?"+urlencode({"q":query,"format":"rss","cc":"CA","setlang":"en"})
    request=urllib.request.Request(endpoint,headers={"Accept":"application/rss+xml, application/xml","User-Agent":"PT-index-feed-reader/1.0"})
    try:
        with urllib.request.urlopen(request,timeout=25) as response:
            body=response.read(2_000_001)
    except urllib.error.HTTPError as e:raise Unavailable(f"HTTP {e.code}") from None
    return parse_rss(body)
def probe(out,fetch=bing_rss,delay=time.sleep):
    # Small feasibility check before considering full collection. Do not treat
    # an RSS feed as a complete engine or a returned result as verified membership.
    obs=[]
    for f in ("M3N","L3S","L7A","P6C","M1E"):
        q=f'{url(f)} "Number of Counsellors in {f}"'
        try:
            raw=fetch(q)
            counts=extract("freeserp",raw,f)
            ids=sorted({i for r in raw["results"] if (i:=profile_id(r["url"]))})
            obs.append({"fsa":f,"query":q,"response":"valid_rss","result_count":len(raw["results"]),"directory_counts":counts,"profile_ids":ids,"response_hash":hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()})
        except Exception as e:
            obs.append({"fsa":f,"query":q,"response":"unavailable","reason":str(e)[:200]})
            if isinstance(e,Unavailable) and any(c in str(e) for c in ("429","403","401")):break
        delay(3)
    report={"source":"Bing published RSS search feed","observations":obs,"tested_areas":len(obs),"valid_responses":sum(r["response"]=="valid_rss" for r in obs),"areas_with_directory_counts":sum(bool(r.get("directory_counts")) for r in obs),"exact_active_competitor_coverage":False}
    Path(out).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    return 0 if len(obs)==5 and all(r.get("directory_counts") for r in obs) else 3
if __name__=="__main__":
    import sys
    raise SystemExit(probe(sys.argv[1] if len(sys.argv)>1 else "bing-rss-probe.json"))
