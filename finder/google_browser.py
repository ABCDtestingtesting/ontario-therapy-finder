"""Free Google Maps browser collector, with per-cell evidence and resumable search jobs.

Does not assume a Google search has succeeded because a page loaded. Saves
links, screenshots on failure, and exact query completion status. Provider
coverage is intrinsically limited to publicly surfaced Google results.
"""
from __future__ import annotations
import csv,hashlib,json,math,os,re,time
from pathlib import Path
from urllib.parse import quote,unquote
from playwright.sync_api import sync_playwright
from .common import SourceUnavailable,InvalidEvidence,write_json,read_json

END_MARKERS=("you've reached the end of the list", "you’ve reached the end of the list",
             'end of the list', 'you have reached the end of the list')
EMPTY_MARKERS=('google maps can’t find', 'google maps can\'t find','no results found',
               'no results for', 'could not find', "didn't match any locations")
CHALLENGE_MARKERS=('unusual traffic from your computer', 'are you a robot',
    'verify you are human','verify that you are a human', 'recaptcha',
    'our systems have detected unusual traffic')


def place_coordinates(url):
    """Read location coordinates, never the map's viewport coordinates."""
    url=unquote(url)
    pair=list(re.finditer(r'!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)',url))
    if pair:
        lat,lon=(float(x) for x in pair[-1].groups())
        return (lat,lon) if 41<lat<57 and -96<lon<-73 else None
    pair=list(re.finditer(r'!2d(-?\d+(?:\.\d+)?)!3d(-?\d+(?:\.\d+)?)',url))
    if pair:
        lon,lat=(float(x) for x in pair[-1].groups())
        return (lat,lon) if 41<lat<57 and -96<lon<-73 else None
    return None


def name_from_url(url):
    match=re.search(r'/maps/place/([^/?#]+)',url)
    if not match:return ''
    return unquote(match.group(1)).replace('+',' ').strip()


def _page_evidence(page):
    """Collect only the actual Google place links present in the search DOM."""
    return page.eval_on_selector_all('a[href*="/maps/place/"]',
        '''anchors => anchors.map(a => ({href:a.href, text:(a.getAttribute('aria-label')||a.innerText||'').trim()}))''')


def _maybe_consent(page):
    # Click an offered consent button, but never try to bypass challenges.
    if 'consent.google' not in page.url and 'before you continue' not in page.title().lower():return
    for label in ('Accept all','Reject all','I agree'):
        b=page.get_by_role('button',name=label,exact=True)
        if b.count():
            b.first.click(timeout=3000)
            page.wait_for_timeout(1000)
            return


def _snapshot(page,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    try:page.screenshot(path=str(path),full_page=False,timeout=10000)
    except Exception:pass


def scan_one(context,query,lat,lon,diagnostics,timeout_seconds=90,max_scroll=35):
    """Scan one actual query. Returns a *complete* search only on verified end.

    Results with unresolved coordinates stay in the evidence for later manual
    review. A page with no proven end marker does not become a zero count.
    """
    diagnostics=Path(diagnostics);diagnostics.mkdir(parents=True,exist_ok=True)
    encoded=quote(query,safe='')
    url=f'https://www.google.com/maps/search/{encoded}/@{lat:.6f},{lon:.6f},16z?hl=en'
    page=context.new_page()
    evidence={'query':query,'search_lat':lat,'search_lon':lon,'search_url':url,
              'place_links':[],'completed':False,'completion_reason':None}
    try:
        page.goto(url,wait_until='domcontentloaded',timeout=35000)
        _maybe_consent(page)
        deadline=time.monotonic()+timeout_seconds
        links={}; stagnant=0; prev_length=-1; prev_height=-1
        while time.monotonic()<deadline:
            try:
                body=page.locator('body').inner_text(timeout=10000).lower()
            except Exception:body=''
            if any(m in body for m in CHALLENGE_MARKERS):
                raise SourceUnavailable('Google Maps presented a human-verification challenge')
            for a in _page_evidence(page):
                url_=a.get('href') or ''
                if '/maps/place/' in url_:
                    links[url_]=a.get('text') or name_from_url(url_)
            if any(m in body for m in END_MARKERS):
                evidence.update(completed=True,completion_reason='visible_end_of_list')
                break
            if any(m in body for m in EMPTY_MARKERS) and not links:
                evidence.update(completed=True,completion_reason='explicit_no_results')
                break
            feeds=page.locator('[role="feed"]')
            if not feeds.count():
                # A single business details page is acceptable ONLY if it has
                # place coordinates and a recognizable place panel.
                if len(links)==1 and place_coordinates(next(iter(links))):
                    heading=page.locator('h1')
                    if heading.count() and heading.first.inner_text(timeout=2000).strip():
                        evidence.update(completed=True,completion_reason='single_place_panel')
                        break
                page.wait_for_timeout(850)
                continue
            feed=feeds.first
            stats=feed.evaluate('''e=>({height:e.scrollHeight,top:e.scrollTop,client:e.clientHeight})''')
            height=stats['height']
            if len(links)==prev_length and height==prev_height:
                stagnant+=1
            else:stagnant=0
            if stagnant>=max_scroll:
                # A stationary feed is NOT proof of total coverage. Preserve
                # evidence and fail rather than silently treating it complete.
                break
            prev_length=len(links);prev_height=height
            feed.evaluate('e=>e.scrollBy(0,Math.max(600,e.clientHeight*0.85))')
            page.wait_for_timeout(650)
        evidence['place_links']=[{'url':k,'name':v,'coordinates':place_coordinates(k)} for k,v in links.items()]
        evidence['page_title']=page.title();evidence['final_url']=page.url
        if not evidence['completed']:
            evidence['failure']='Google Maps search did not display a verified list ending'
            _snapshot(page,diagnostics/'google_unverified.png')
            raise SourceUnavailable(evidence['failure'])
        return evidence
    except Exception:
        if not evidence['place_links']:
            try:
                evidence['place_links']=[{'url':a['href'],'name':a.get('text',''),
                        'coordinates':place_coordinates(a['href'])} for a in _page_evidence(page)]
            except Exception:pass
        _snapshot(page,diagnostics/'google_failure.png')
        raise
    finally:
        write_json(diagnostics/'search_evidence.json',evidence)
        page.close()


def grid_points(bbox,cell_km=1.0,max_cells=20000):
    """bbox = (south,west,north,east); every centre within a 1 km grid."""
    south,west,north,east=bbox
    if south>=north or west>=east or cell_km<=0:raise ValueError('Invalid grid')
    lat_step=cell_km/111.05
    mid=(south+north)/2
    lon_step=cell_km/(111.05*max(math.cos(math.radians(mid)),0.25))
    rows=math.ceil((north-south)/lat_step)
    cols=math.ceil((east-west)/lon_step)
    if rows*cols>max_cells:raise InvalidEvidence(f'Grid requires {rows*cols} cells; limit {max_cells}')
    for r in range(rows):
        for c in range(cols):
            yield round(south+(r+0.5)*(north-south)/rows,6),round(west+(c+0.5)*(east-west)/cols,6)


def collect(bbox,queries,out_csv,progress=lambda x:None,headless=None,cancel_requested=lambda:False,context_factory=None):
    """Collect grid queries with durable checkpoints. No successful but empty CSV."""
    out_csv=Path(out_csv);out_csv.parent.mkdir(parents=True,exist_ok=True)
    work=out_csv.parent/'firefox_evidence';work.mkdir(exist_ok=True)
    plan=[(i,j,lat,lon,q) for i,(lat,lon) in enumerate(grid_points(bbox)) for j,q in enumerate(queries)]
    signature=hashlib.sha256(json.dumps(plan).encode()).hexdigest()
    checkpoint=work/'checkpoint.json'
    cache=read_json(checkpoint,{'signature':signature,'completed':{},'locations':{},'unlocated':{}})
    if cache.get('signature')!=signature:raise InvalidEvidence('Existing Google grid differs from current plan; manual reset needed')
    if headless is None:headless=bool(os.environ.get('CI'))
    with sync_playwright() as pw:
        context=(context_factory(pw) if context_factory else pw.firefox.launch_persistent_context(
            str(work/'browser_profile'),headless=headless,viewport={'width':1400,'height':960},locale='en-CA'))
        try:
            for i,j,lat,lon,query in plan:
                job=f'{i:06d}_{j}'
                if job in cache['completed']:continue
                if cancel_requested():raise SourceUnavailable('Google Maps scan stopped; progress saved')
                progress(f'Google Maps {len(cache["completed"])+1}/{len(plan)}: {query} at {lat},{lon}')
                evidence=scan_one(context,query,lat,lon,work/job)
                cache['completed'][job]={'reason':evidence['completion_reason'],'query':query,'lat':lat,'lon':lon}
                for link in evidence['place_links']:
                    url=link['url'];coords=link['coordinates']
                    key=url.split('?')[0].lower()
                    if coords:
                        la,lo=coords
                        cache['locations'][key]={'title':link['name'] or name_from_url(url),
                             'latitude':la,'longitude':lo,'link':url,'category':query,'place_id':key}
                    else:cache['unlocated'][key]=link
                write_json(checkpoint,cache)
        finally:context.close()
    if len(cache['completed'])!=len(plan):raise InvalidEvidence('Google grid checkpoint incomplete')
    if cache['unlocated']:
        raise InvalidEvidence(f'{len(cache["unlocated"])} Google business links lack coordinates. Evidence saved.')
    if not cache['locations']:
        raise InvalidEvidence('All grid searches found zero businesses; do not certify without independent verification')
    rows=list(cache['locations'].values())
    with out_csv.open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=['title','latitude','longitude','link','category','place_id'])
        writer.writeheader();writer.writerows(rows)
    return {'cells':len(plan),'locations':len(rows),'output':str(out_csv)}
