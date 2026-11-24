"""No-account search source probe. Use only official anonymous endpoints."""
import json,re,urllib.request,urllib.error,csv,time,datetime,hashlib,os,tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from zoneinfo import ZoneInfo
TORONTO=ZoneInfo("America/Toronto")
EXA="https://mcp.exa.ai/mcp"
TAVILY="https://api.tavily.com/search"
class Unavailable(RuntimeError):pass
def request(url,obj,headers=None):
    h={"Content-Type":"application/json","Accept":"application/json, text/event-stream","User-Agent":"PT-weekly-keyless-probe/1.0"}
    h.update(headers or {})
    req=urllib.request.Request(url,data=json.dumps(obj).encode(),headers=h)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read(2_000_001)
            if len(raw)>2_000_000:raise Unavailable("Response exceeds size cap")
            return raw.decode(),dict(r.headers.items())
    except urllib.error.HTTPError as e:raise Unavailable(f"HTTP {e.code}") from None
def unpack(raw):
    try:return json.loads(raw)
    except json.JSONDecodeError:
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    obj=json.loads(line[5:])
                    if "result" in obj or "error" in obj:return obj
                except json.JSONDecodeError:pass
        raise Unavailable("Unrecognized server response")
def rpc(method,params,session=None,id=1):
    h={"MCP-Protocol-Version":"2025-03-26"}
    if session:h["Mcp-Session-Id"]=session
    raw,headers=request(EXA,{"jsonrpc":"2.0","id":id,"method":method,"params":params},h)
    obj=unpack(raw)
    if obj.get("error"):raise Unavailable("MCP error: "+str(obj["error"])[:200])
    if obj.get("id")!=id or "result" not in obj:raise Unavailable("Missing matching MCP response")
    return obj["result"],{k.lower():v for k,v in headers.items()}
def exa(query, num_results=10):
    # Initialize using MCP's public endpoint; no credentials or billing.
    hello,headers=rpc("initialize",{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"pt-weekly-probe","version":"1.0"}})
    session=headers.get("mcp-session-id")
    h={"MCP-Protocol-Version":hello.get("protocolVersion","2025-03-26")}
    if session:h["Mcp-Session-Id"]=session
    request(EXA,{"jsonrpc":"2.0","method":"notifications/initialized"},h)
    tools,_=rpc("tools/list",{},session,2)
    tool=next((t for t in tools.get("tools",[]) if t["name"]=="web_search_exa"),None)
    if not tool:raise Unavailable("Public web search tool missing")
    props=tool.get("inputSchema",{}).get("properties",{})
    args={"query":query}
    if "numResults" in props:args["numResults"]=num_results
    if "type" in props and "fast" in props["type"].get("enum",[]):args["type"]="fast"
    result,_=rpc("tools/call",{"name":"web_search_exa","arguments":args},session,3)
    metadata = result.get("_meta") or {}
    if isinstance(metadata, dict) and metadata.get("ai.exa/rateLimited"):
        raise Unavailable("Exa rate limit reached")
    if result.get("isError"):
        raise Unavailable("Exa tool returned an error")
    return result
def tavily(query):
    raw,_=request(TAVILY,{"query":query,"search_depth":"basic","max_results":10,"include_answer":False,"include_raw_content":False,"auto_parameters":False},{"X-Tavily-Access-Mode":"keyless","X-Client-Source":"tavily-python-keyless","Accept":"application/json"})
    obj=json.loads(raw)
    if not isinstance(obj.get("results"),list):raise Unavailable("No search results field")
    return obj
def profiles(obj):
    urls=re.findall(r'https://(?:www\.)?psychologytoday\.com/ca/therapists/[^/\s"\\]+/(\d{4,12})(?=[/?#\s"\\]|$)',json.dumps(obj,ensure_ascii=False))
    return sorted(set(urls))
def profile_id(url):
    try:u=urlsplit(url)
    except ValueError:return None
    if u.scheme!="https" or u.hostname not in ("psychologytoday.com","www.psychologytoday.com"):return None
    m=re.fullmatch(r"/ca/therapists/[^/]+/(\d{4,12})/?",u.path,re.I)
    return m.group(1) if m else None
def mentions_fsa(text,fsa):
    return bool(re.search(r"(?<![A-Z0-9])"+re.escape(fsa)+r"(?:[ ]?\d[A-Z]\d)?(?![A-Z0-9])",text,re.I))
def indexed_evidence(source,obj,fsa):
    # Match exact postal text only in a single result's own title/snippet/highlight.
    # A text mention is not proof of active advertised-area membership.
    found=set(); scoped=set(); dates={}
    if source=="freeserp":
        rows=obj.get("results")
        if not isinstance(rows,list) or any(not isinstance(x,dict) or not isinstance(x.get("url"),str) for x in rows):
            raise Unavailable("Malformed FreeSerp result row")
        for x in rows:
            i=profile_id(x["url"])
            if not i:continue
            found.add(i)
            if mentions_fsa(" ".join(str(x.get(k) or "") for k in ("title","snippet")),fsa):
                scoped.add(i)
            meta=x.get("source")
            captured=(meta.get("captured_at") if isinstance(meta,dict) else None) or x.get("crawled_at")
            if isinstance(captured,str) and re.match(r"^\d{4}-\d{2}-\d{2}",captured):dates[i]=captured[:10]
    elif source=="exa":
        blocks=obj.get("content")
        if not isinstance(blocks,list):raise Unavailable("Malformed Exa content")
        for b in blocks:
            if not isinstance(b,dict) or not isinstance(b.get("text"),str):continue
            raw=b["text"]
            # Exa returns text result records. Split on result title headers, and
            # accept a postal mention only where exactly one profile URL is present.
            parts=re.split(r"(?im)(?=^\s*(?:\d+\.\s*)?(?:Title|URL):\s*)",raw)
            # Recombine title followed by its URL; never attach an unrelated result's text.
            pending=""
            for part in parts:
                if not part.strip():continue
                if re.match(r"(?im)^\s*(?:\d+\.\s*)?Title:",part):
                    pending=part;continue
                chunk=pending+part;pending=""
                ids=profiles(chunk);found.update(ids)
                if len(ids)==1 and mentions_fsa(chunk,fsa):scoped.add(ids[0])
            if pending:
                ids=profiles(pending);found.update(ids)
                if len(ids)==1 and mentions_fsa(pending,fsa):scoped.add(ids[0])
        # Preserve additional URL discoveries separately; do not attribute their geography.
        found.update(profiles(obj))
    else:raise ValueError("Unsupported source")
    return sorted(found),sorted(scoped),dates
def get_json(url,params):
    req=urllib.request.Request(url+"?"+urlencode(params),headers={"Accept":"application/json","User-Agent":"PT-weekly-keyless-probe/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read(2_000_001)
            if len(raw)>2_000_000:raise Unavailable("Response exceeds size cap")
            return json.loads(raw)
    except urllib.error.HTTPError as e:raise Unavailable(f"HTTP {e.code}") from None
def freeserp(query, size=100):
    obj=get_json("https://freeserp.ai/api.php",{"index":"web","q":query,"size":size})
    if not isinstance(obj,dict) or obj.get("ok") is not True or not isinstance(obj.get("results"),list):
        raise Unavailable("Unrecognized FreeSerp response")
    return obj
def mwmbl(query):
    obj=get_json("https://api.mwmbl.org/api/v2/search/",{"q":query})
    if not isinstance(obj,(dict,list)):raise Unavailable("Unrecognized Mwmbl response")
    return obj
def survey(output=None, baseline=None, sources=None, delay=time.sleep, resume=False):
    # These are discovery observations, never current or complete PT membership.
    root=Path(__file__).resolve().parent
    output=Path(output) if output else root/"keyless-observations.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    with (Path(baseline) if baseline else root/"candidates.csv").open(newline="",encoding="utf8") as f: rows=list(csv.DictReader(f))
    if len(rows)!=60 or len({r["fsa"] for r in rows})!=60:raise ValueError("Expected 60 distinct FSAs")
    report={"schema_version":2,"survey_day":datetime.datetime.now(TORONTO).date().isoformat(),"started_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "exact_active_advertiser_ranking_certified":False,"source_scope":"third-party search index; no verified active directory membership",
            "observations":[]}
    expected={(r["fsa"],name,v) for r in rows for name in ("freeserp","exa") for v in range(2)}
    populations={r["fsa"]:int(r["census_population_2021"]) for r in rows}
    retained={}
    if resume and output.exists():
        old=json.loads(output.read_text(encoding="utf8"))
        for x in old.get("observations",[]) if old.get("schema_version")==2 and old.get("survey_day")==report["survey_day"] else []:
            key=(x.get("fsa"),x.get("source"),x.get("variant"))
            if key in expected and x.get("population_2021")==populations[key[0]] and x.get("status") in ("indexed_leads_only","no_indexed_leads_not_zero_competitors") and isinstance(x.get("ids"),list) and isinstance(x.get("postal_text_ids"),list) and re.fullmatch(r"[a-f0-9]{64}",str(x.get("response_hash",""))):
                retained[key]=x
        if retained:report["started_at"]=old.get("started_at",report["started_at"])
    report["observations"]=list(retained.values())
    def save():
        with tempfile.NamedTemporaryFile(mode="w",dir=output.parent,encoding="utf8",delete=False) as tmp:
            os.chmod(tmp.name,0o600);json.dump(report,tmp,indent=2);name=tmp.name
        os.replace(name,output)
    stopped={}
    providers=sources if sources is not None else [("freeserp",freeserp),("exa",exa)]
    if {name for name,_ in providers}!={"freeserp","exa"} or len(providers)!=2:raise ValueError("Expected both anonymous sources")
    save()
    for row in rows:
        fsa=row["fsa"]
        for name,fn in providers:
            for variant in range(2):
                if (fsa,name,variant) in retained:continue
                query=[f'site:psychologytoday.com/ca/therapists/ "{fsa}" Ontario therapist',
                       f'site:psychologytoday.com/ca/therapists/ "{fsa}" Ontario counselling online'][variant]
                item={"fsa":fsa,"source":name,"variant":variant,"query":query,
                      "population_2021":int(row["census_population_2021"]),
                      "observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat()}
                if name in stopped:item.update(status="source_stopped",reason=stopped[name],ids=None)
                else:
                    try:
                        obj=fn(query)
                        found,scoped,dates=indexed_evidence(name,obj,fsa)
                        if name=="freeserp":item["returned_rows"]=len(obj["results"])
                        item.update(status="indexed_leads_only" if found else "no_indexed_leads_not_zero_competitors",ids=found,
                                    postal_text_ids=scoped,index_capture_dates=dates,
                                    response_hash=hashlib.sha256(json.dumps(obj,sort_keys=True).encode()).hexdigest())
                    except Exception as e:
                        reason=f"{type(e).__name__}: {str(e)[:200]}"
                        item.update(status="unavailable",reason=reason,ids=None)
                        if isinstance(e,Unavailable) and ("429" in reason or "rate limit" in reason.lower() or "401" in reason or "403" in reason or "402" in reason):stopped[name]=reason
                    delay(1)
                report["observations"].append(item);save()
                print(fsa,name,variant,item["status"],len(item["ids"]) if item["ids"] is not None else "-",flush=True)
    report["finished_at"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["coverage"]={name:{"areas_with_leads":len({x["fsa"] for x in report["observations"] if x["source"]==name and x.get("ids")}),
       "areas_with_two_responses":sum(all(any(x["fsa"]==r["fsa"] and x["source"]==name and x["variant"]==v and x["ids"] is not None for x in report["observations"]) for v in range(2)) for r in rows)}
       for name in ("freeserp","exa")}
    save();print(json.dumps(report["coverage"],indent=2),flush=True)
    # A completed probe is evidence collection only; exact-ranking gate remains closed.
    return 0 if len(report["observations"])==240 and all(x["areas_with_two_responses"]==60 for x in report["coverage"].values()) else 3
def main():
    import sys
    if "--survey" in sys.argv:return survey()
    query='site:psychologytoday.com/ca/therapists/ "L3S" Markham Ontario therapist'
    failures=0
    for name,fn in [("exa",exa),("tavily",tavily),("freeserp",freeserp),("mwmbl",mwmbl)]:
        try:
            p=profiles(fn(query));print(name,"unique indexed profile IDs",len(p),flush=True)
            if not p:failures+=1
        except Exception as e:
            print(name,"UNAVAILABLE",type(e).__name__,str(e)[:250],flush=True);failures+=1
    return failures
if __name__=="__main__":raise SystemExit(main())
