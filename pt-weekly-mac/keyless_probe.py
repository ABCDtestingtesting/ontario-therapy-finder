"""No-account search source probe. Use only official anonymous endpoints."""
import json,re,urllib.request,urllib.error,csv,time,datetime,hashlib
from pathlib import Path
from urllib.parse import urlsplit, urlencode
EXA="https://mcp.exa.ai/mcp"
TAVILY="https://api.tavily.com/search"
class Unavailable(RuntimeError):pass
def request(url,obj,headers=None):
    h={"Content-Type":"application/json","Accept":"application/json, text/event-stream","User-Agent":"PT-weekly-keyless-probe/1.0"}
    h.update(headers or {})
    req=urllib.request.Request(url,data=json.dumps(obj).encode(),headers=h)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            return r.read(2_000_000).decode(),dict(r.headers.items())
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
def survey():
    # These are discovery observations, never current or complete PT membership.
    root=Path(__file__).resolve().parent
    output=root/"keyless-observations.json"
    with (root/"candidates.csv").open(newline="",encoding="utf8") as f: rows=list(csv.DictReader(f))
    if len(rows)!=60 or len({r["fsa"] for r in rows})!=60:raise ValueError("Expected 60 distinct FSAs")
    report={"schema_version":1,"started_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "exact_active_advertiser_ranking_certified":False,"source_scope":"third-party search index; no verified active directory membership",
            "observations":[]}
    def save():
        temp=output.with_suffix(".tmp");temp.write_text(json.dumps(report,indent=2),encoding="utf8");temp.replace(output)
    stopped={}
    for row in rows:
        fsa=row["fsa"]
        for name,fn in [("freeserp",freeserp),("exa",exa)]:
            for variant in range(2):
                query=[f'site:psychologytoday.com/ca/therapists/ "{fsa}" Ontario therapist',
                       f'site:psychologytoday.com/ca/therapists/ "{fsa}" Ontario counselling online'][variant]
                item={"fsa":fsa,"source":name,"variant":variant,"query":query,
                      "population_2021":int(row["census_population_2021"]),
                      "observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat()}
                if name in stopped:item.update(status="source_stopped",reason=stopped[name],ids=None)
                else:
                    try:
                        obj=fn(query)
                        if name=="freeserp":
                            # Use only top-level result URLs, not incidental links in snippets.
                            data=obj["results"]
                            if any(not isinstance(x,dict) or not isinstance(x.get("url"),str) for x in data):
                                raise Unavailable("Malformed result row")
                            urls=[x["url"] for x in data]
                            found=profiles(urls)
                            item["returned_rows"]=len(data)
                        else:found=profiles(obj)
                        item.update(status="indexed_leads_only" if found else "no_indexed_leads_not_zero_competitors",ids=found,
                                    response_hash=hashlib.sha256(json.dumps(obj,sort_keys=True).encode()).hexdigest())
                    except Exception as e:
                        reason=f"{type(e).__name__}: {str(e)[:200]}"
                        item.update(status="unavailable",reason=reason,ids=None)
                        if isinstance(e,Unavailable) and ("429" in reason or "rate limit" in reason.lower() or "401" in reason or "403" in reason or "402" in reason):stopped[name]=reason
                    time.sleep(1)
                report["observations"].append(item);save()
                print(fsa,name,variant,item["status"],len(item["ids"]) if item["ids"] is not None else "-",flush=True)
    report["finished_at"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["coverage"]={name:{"areas_with_leads":len({x["fsa"] for x in report["observations"] if x["source"]==name and x.get("ids")}),
       "areas_with_two_responses":sum(all(any(x["fsa"]==r["fsa"] and x["source"]==name and x["variant"]==v and x["ids"] is not None for x in report["observations"]) for v in range(2)) for r in rows)}
       for name in ("freeserp","exa")}
    save();print(json.dumps(report["coverage"],indent=2),flush=True)
    # A completed probe is evidence collection only; exact-ranking gate remains closed.
    return 0 if len(report["observations"])==240 else 1
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
