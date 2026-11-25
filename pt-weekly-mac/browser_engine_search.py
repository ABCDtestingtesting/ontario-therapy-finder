"""Search public browser result pages without requiring a metasearch server.
Respect access restrictions; never solve challenges or route around denials.
Counts are independent index evidence, not directory membership.
"""
import csv,json,time,datetime as dt,re,base64
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs,unquote
from playwright.sync_api import sync_playwright
from keyless_probe import profile_id,mentions_fsa
from directory_index import exact_url,extract_count
ROOT=Path(__file__).resolve().parent
ENGINES={
 "google":("https://www.google.ca/search","q"),
 "bing":("https://www.bing.com/search","q"),
 "duckduckgo":("https://duckduckgo.com/","q"),
 "brave":("https://search.brave.com/search","q"),
 "startpage":("https://www.startpage.com/sp/search","query"),
 "yahoo":("https://search.yahoo.com/search","p"),
 "mojeek":("https://www.mojeek.com/search","q"),
 "yandex":("https://yandex.com/search/","text"),
 "qwant":("https://www.qwant.com/","q"),
 "ecosia":("https://www.ecosia.org/search","q")
}
RESTRICT=re.compile(r"(?i)\b(?:verify (?:that )?you are (?:a )?human|checking your browser|access denied|request blocked|unusual traffic|automated queries|captcha|just a moment|too many requests|security challenge)\b")
def destination(url,engine):
    # Decode ordinary search-result redirect links without visiting destination.
    try:
        u=urlsplit(url);q=parse_qs(u.query);host=u.hostname or ""
        if host in ("www.psychologytoday.com","psychologytoday.com"):return url
        if engine=="google" and host in ("www.google.ca","www.google.com","google.com") and u.path=="/url":
            return q.get("url",q.get("q",[""]))[0]
        if engine=="duckduckgo" and host.endswith(".duckduckgo.com") and u.path.startswith("/l/"):return q.get("uddg",[""])[0]
        if engine=="yahoo" and (host=="r.search.yahoo.com" or host.endswith(".search.yahoo.com")):
            m=re.search(r"/RU=([^/]+)",u.path)
            if m:return unquote(m.group(1))
        if engine=="bing" and host=="www.bing.com" and u.path.startswith("/ck/"):
            v=q.get("u",[""])[0]
            if v.startswith("a1"):return base64.urlsafe_b64decode(v[2:]+"="*(-len(v[2:])%4)).decode()
    except (ValueError,UnicodeError):pass
    return ""
def parse(fsa,engine,links):
    records={};ids=set();counts=set()
    for x in links:
        url=destination(x.get("href",""),engine);pid=profile_id(url)
        direct=exact_url(url,fsa)
        snippet=x.get("snippet","");title=x.get("title","")
        if not direct and not (pid and mentions_fsa(title+" "+snippet,fsa)):continue
        records[url]={"url":url,"title":title[:300],"engine":engine}
        if pid:ids.add(pid)
        if direct:
            c=extract_count(snippet,fsa)
            if c:counts.add(c)
    return dict(relevant_results=list(records.values()),postal_profile_ids=sorted(ids),directory_counts=sorted(counts))
def run(out,limit=None):
    with (ROOT/"candidates.csv").open() as f:areas=[r["fsa"] for r in csv.DictReader(f)]
    if limit is not None:areas=areas[:limit]
    out=Path(out);out.mkdir(exist_ok=True,parents=True)
    rows=[];stopped={};last={}
    def save():
        coverage={e:{"attempted":sum(x["engine"]==e and x["status"]!="stopped_due_to_restriction" for x in rows),"areas_with_relevant_results":sum(x["engine"]==e and x["status"]=="relevant_results" for x in rows),"areas_with_directory_counts":sum(x["engine"]==e and bool(x["directory_counts"]) for x in rows),"restriction":stopped.get(e)} for e in ENGINES}
        report={"areas":len(areas),"coverage":coverage,"all_engines_verified":bool(areas) and all(x["areas_with_relevant_results"]==len(areas) for x in coverage.values()),"method":"Public Firefox search result pages; exact directory links and postal-text profile leads."}
        for path,data in ((out/"engine-evidence.json",rows),(out/"engine-coverage.json",report)):
            tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(data,indent=2));tmp.replace(path)
        return report
    save()
    with sync_playwright() as p:
        browser=p.firefox.launch(headless=False)
        ctx=browser.new_context(locale="en-CA",viewport={"width":1280,"height":900})
        page=ctx.new_page()
        try:
            for fsa in areas:
                for engine,(base,param) in ENGINES.items():
                    q=f'site:psychologytoday.com/ca/therapists/ "{fsa}" Ontario therapist'
                    row=dict(fsa=fsa,engine=engine,query=q,observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),relevant_results=[],postal_profile_ids=[],directory_counts=[],errors=[])
                    if engine in stopped:row.update(status="stopped_due_to_restriction",errors=[stopped[engine]])
                    else:
                        try:
                            time.sleep(max(0,10-(time.monotonic()-last.get(engine,0))))
                            last[engine]=time.monotonic()
                            resp=page.goto(base+"?"+urlencode({param:q}),wait_until="domcontentloaded",timeout=16000)
                            code=resp.status if resp else 0
                            body=page.locator("body").inner_text(timeout=6000)
                            if code in (401,403,429) or RESTRICT.search(body[:2200]) or RESTRICT.search(page.title()):
                                reason=f"HTTP {code} or browser access restriction";stopped[engine]=reason
                                row.update(status="unavailable",errors=[reason])
                            elif code!=200:row.update(status="unavailable",errors=[f"HTTP {code}"])
                            else:
                                # Wait briefly for client-rendered results, not for challenges.
                                try:page.wait_for_function("()=>Array.from(document.querySelectorAll('a[href]')).some(a=>a.href.includes('psychologytoday.com') && a.getClientRects().length)",timeout=1800)
                                except Exception:pass
                                links=page.locator("a[href]").evaluate_all("""as=>as.filter(a=>a.getClientRects().length && getComputedStyle(a).visibility!=='hidden').map(a=>{const el=a.closest('li.b_algo,.g,.result,.web-result,.snippet,article,[data-testid="result"],.algo,.w-gl__result')||a.parentElement;return {href:a.href,title:a.innerText,snippet:(el?.innerText||'').slice(0,1800)}})""")
                                row.update(parse(fsa,engine,links))
                                row["status"]="relevant_results" if row["relevant_results"] else "no_relevant_results"
                                # Consent or CAPTCHA gates appearing late must stop this source.
                                if RESTRICT.search(page.locator("body").inner_text(timeout=5000)[:2200]):
                                    reason="Browser access restriction";stopped[engine]=reason;row.update(status="unavailable",errors=[reason],relevant_results=[],postal_profile_ids=[],directory_counts=[])
                        except Exception as e:
                            row.update(status="unavailable",errors=[f"{type(e).__name__}: {str(e)[:180]}"])
                    rows.append(row);save()
                    print(fsa,engine,row["status"],len(row["relevant_results"]),flush=True)
        finally:ctx.close();browser.close()
    report=save();print(json.dumps(report,indent=2),flush=True);return 0 if report["all_engines_verified"] else 3
if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--out",required=True);parser.add_argument("--limit",type=int);a=parser.parse_args()
    raise SystemExit(run(a.out,a.limit))
