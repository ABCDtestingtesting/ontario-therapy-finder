"""Independent live macOS acceptance check of the PT Weekly Decision page contract."""
import csv,json,time,re,hashlib,datetime as dt,sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urljoin
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
OUT=Path("decision-live-evidence")
OUT.mkdir(exist_ok=True)
HOSTS={"www.psychologytoday.com","psychologytoday.com"}
class AccessStopped(Exception):pass
def target(fsa,n=1):return "https://www.psychologytoday.com/ca/therapists/"+fsa.lower()+(f"?page={n}" if n>1 else "")
def page_number(u,fsa):
    p=urlsplit(u);q=parse_qs(p.query)
    if p.scheme!="https" or p.hostname not in HOSTS or p.path.rstrip("/").lower()!="/ca/therapists/"+fsa.lower() or set(q)-{"page"}:return None
    try:return int(q.get("page",["1"])[0]) if len(q.get("page",["1"]))==1 else None
    except ValueError:return None
def parse(fsa,n,url,text,links,status):
    if status in (401,403,429) or re.search(r"(?i)\b(?:verify you are human|checking your browser|access denied|request blocked|unusual traffic|just a moment)\b",text[:1800]):
        raise AccessStopped(f"HTTP {status} or access restriction")
    if status!=200 or page_number(url,fsa)!=n:raise ValueError("Unexpected status or URL")
    if not re.search(r"(?im)^\s*(?:Find )?Therapists in\s+"+re.escape(fsa)+r"\s*$",text):raise ValueError("Missing expected directory heading")
    count=re.search(r"Number of Counsellors in\s+"+re.escape(fsa)+r"\s*(<\s*\d+|[\d,]+\+?)",text,re.I)
    if not count:raise ValueError("Missing directory statistic")
    label=re.sub(r"[\s,]","",count.group(1))
    ids=set();view_ids=set();pages=set();next_pages=set();unlinked_next=False
    for link in links:
        u=urljoin(url,link.get("href",""));t=link.get("text","").strip();a=link.get("aria","").strip();rel=link.get("rel","");p=urlsplit(u)
        m=re.fullmatch(r"/ca/therapists/[^/]+/(\d{4,12})/?",p.path,re.I) if p.scheme=="https" and p.hostname in HOSTS else None
        if m and t:
            ids.add(m.group(1))
            if re.fullmatch(r"View(?: profile)?",t,re.I) or re.fullmatch(r"View(?: profile)?",a,re.I):view_ids.add(m.group(1))
        pn=page_number(u,fsa)
        nxt=bool(re.fullmatch(r"Next(?: page)?",t,re.I) or re.fullmatch(r"Next(?: page)?",a,re.I) or "next" in rel.split())
        if pn is not None and pn>0:
            if t.isdigit() or nxt or re.fullmatch(r"Previous(?: page)?",t,re.I):pages.add(pn)
            if nxt:next_pages.add(pn)
        elif nxt:unlinked_next=True
    if not ids or not view_ids or ids-view_ids:raise ValueError("Unmatched or absent result-card links")
    if unlinked_next or any(p!=n+1 for p in next_pages):raise ValueError("Unexpected Next link")
    if n+1 in pages:next_page=n+1
    elif any(p>n for p in pages):raise ValueError("Pagination skips next page")
    else:next_page=None
    if n>1 and not pages:raise ValueError("Pagination missing on later page")
    if next_page is None and re.search(r"(?im)^\s*Next\s*$",text):raise ValueError("Next control without valid link")
    return {"page":n,"url":url,"ids":sorted(ids),"directory_label":label,"pagination_links":sorted(pages),"next_page":next_page,"observed_at":dt.datetime.now(dt.timezone.utc).isoformat()}
def main():
    with (ROOT/"candidates.csv").open() as f:areas=list(csv.DictReader(f))
    assert len(areas)==len({r["fsa"] for r in areas})==60
    # Count actual elapsed time, including browser startup. One normal browser,
    # no proxies or identity changes; stop immediately on server restrictions.
    started=time.monotonic();last=0;state={};restricted=False;attempts=0
    def checkpoint():
        rows=[]
        for a in areas:
            f=a["fsa"];s=state.get(f,{})
            ids=set(i for p in s.get("pages",[]) for i in p["ids"])
            rows.append({"fsa":f,"population":int(a["census_population_2021"]),"status":s.get("status","not_scanned"),"pages":len(s.get("pages",[])),"unique_visible_ids":len(ids),"error":s.get("error","")})
        completed=sum(r["status"]=="complete" for r in rows)
        status={"areas":60,"attempted_pages":attempts,"areas_completed":completed,"areas_with_pages":sum(r["pages"]>0 for r in rows),"elapsed_seconds":round(time.monotonic()-started,3),"access_stopped":restricted,"full_live_verification":completed==60 and time.monotonic()-started<=3600}
        (OUT/"status.json").write_text(json.dumps(status,indent=2));(OUT/"pages.json").write_text(json.dumps(state,indent=2))
        with (OUT/"areas.csv").open("w") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        print(json.dumps(status),flush=True)
        return status
    checkpoint()
    try:
        with sync_playwright() as pw:
            ctx=pw.firefox.launch_persistent_context(str(OUT/"profile"),headless=False,locale="en-CA",viewport={"width":1280,"height":900})
            page=ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                while time.monotonic()-started<3565:
                    pending=[a for a in areas if state.get(a["fsa"],{}).get("status","pending")=="pending"]
                    if not pending:break
                    # First-pass coverage, then complete each remaining chain.
                    a=min(pending,key=lambda a:(bool(state.get(a["fsa"],{}).get("pages")),len(state.get(a["fsa"],{}).get("pages",[]))))
                    f=a["fsa"];s=state.setdefault(f,{"status":"pending","pages":[]});n=len(s["pages"])+1
                    try:
                        time.sleep(max(0,10-(time.monotonic()-last)))
                        if time.monotonic()-started>=3565:break
                        last=time.monotonic();attempts+=1
                        response=page.goto(target(f,n),wait_until="domcontentloaded",timeout=45000)
                        status=response.status if response else 0
                        if status in (401,403,429):raise AccessStopped(f"HTTP {status}")
                        try:page.wait_for_function("""fsa => { const t=document.body?.innerText||''; return t.includes('Number of Counsellors in '+fsa) && Array.from(document.querySelectorAll('a[href]')).some(a=>/^View(?: profile)?$/i.test(a.innerText.trim()) && a.getClientRects().length); }""",arg=f,timeout=12000)
                        except Exception:pass
                        text=page.locator("body").inner_text(timeout=20000)
                        links=page.locator("a[href]").evaluate_all("""as=>as.filter(a=>a.getClientRects().length && getComputedStyle(a).visibility!=='hidden').map(a=>({href:a.href,text:a.innerText,aria:a.getAttribute('aria-label')||'',rel:a.rel||''}))""")
                        rec=parse(f,n,page.url,text,links,status);rec["navigation_seconds"]=round(time.monotonic()-last,3)
                        old=set(i for p in s["pages"] for i in p["ids"])
                        if not set(rec["ids"])-old:raise ValueError("Repeated page")
                        if s["pages"] and s["pages"][0]["directory_label"]!=rec["directory_label"]:raise ValueError("Directory label changed")
                        s["pages"].append(rec)
                        if rec["next_page"] is None:
                            if not rec["directory_label"].startswith("<") and len(old|set(rec["ids"]))<int(rec["directory_label"].rstrip("+")):raise ValueError("Below displayed lower bound")
                            s["status"]="complete"
                    except AccessStopped as e:
                        s.update(status="access_stopped",error=str(e));restricted=True
                        page.screenshot(path=str(OUT/"restriction.png"));checkpoint();break
                    except Exception as e:
                        s.update(status="incomplete",error=str(e)[:300]);print(f,n,s["error"],flush=True)
                    checkpoint()
            finally:ctx.close()
    except Exception as e:print(type(e).__name__,str(e)[:500],flush=True)
    return 0 if checkpoint()["full_live_verification"] else 3
if __name__=="__main__":raise SystemExit(main())
