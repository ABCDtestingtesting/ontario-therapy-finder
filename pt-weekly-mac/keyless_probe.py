"""No-account search source probe. Use only official anonymous endpoints."""
import json,re,urllib.request,urllib.error
from urllib.parse import urlsplit
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
def exa(query):
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
    if "numResults" in props:args["numResults"]=10
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
def main():
    query='site:psychologytoday.com/ca/therapists/ "L3S" Markham Ontario therapist'
    failures=0
    for name,fn in [("exa",exa),("tavily",tavily)]:
        try:
            p=profiles(fn(query));print(name,"unique indexed profile IDs",len(p),flush=True)
            if not p:failures+=1
        except Exception as e:
            print(name,"UNAVAILABLE",type(e).__name__,str(e)[:250],flush=True);failures+=1
    return failures
if __name__=="__main__":raise SystemExit(main())
