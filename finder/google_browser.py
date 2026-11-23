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
from .common import SourceUnavailable,InvalidEvidence,HumanVerificationRequired,write_json,read_json

END_MARKERS=("you've reached the end of the list", "you’ve reached the end of the list",
             'end of the list', 'you have reached the end of the list')
EMPTY_MARKERS=('google maps can’t find', 'google maps can\'t find','no results found',
               'no results for', 'could not find', "didn't match any locations")
CHALLENGE_MARKERS=('unusual traffic from your computer', 'are you a robot',
    'verify you are human','verify that you are a human', 'recaptcha',
    'our systems have detected unusual traffic','too many requests',
    'access denied','request blocked','429 too many requests')


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


def _refresh_map_area_results(page, lat, lon):
    """Force Google Maps to use the actual displayed map instead of distant
    search suggestions. Live Firefox tests showed unchecked 'Update results
    when map moves' returned remote clinics for rural Ontario FSAs; checking
    the visible control and panning made Google report genuine local results
    or an explicit 'No results' message. Fail closed when UI changes.
    """
    control = page.get_by_text('Update results when map moves')
    if not control.count() or not control.first.is_visible():
        raise SourceUnavailable('Google location-scoped results control was not visible')
    original_url = page.url
    control.first.click(timeout=5000)
    page.wait_for_timeout(500)
    viewport = page.viewport_size or {'width':1400,'height':960}
    x = int(viewport['width'] * .72)
    y = int(viewport['height'] * .52)
    # A reversible drag triggers Google's live 'update results when map moves'
    # query while returning the map center to its original geographic tile.
    for dx,dy in ((165,45),(-165,-45)):
        page.mouse.move(x,y)
        page.mouse.down()
        page.mouse.move(x+dx,y+dy,steps=14)
        page.mouse.up()
        page.wait_for_timeout(1800)
    refreshed_url=page.url
    match=re.search(r'/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),',refreshed_url)
    if refreshed_url == original_url or not match:
        raise SourceUnavailable('Google did not confirm map-area results refresh')
    new_lat,new_lon=map(float,match.groups())
    radians=math.pi/180
    value=math.sin((new_lat-lat)*radians/2)**2+(
        math.cos(lat*radians)*math.cos(new_lat*radians)
        *math.sin((new_lon-lon)*radians/2)**2)
    offset=12742*math.asin(min(1,math.sqrt(value)))
    if offset > .70:
        raise SourceUnavailable(f'Google map center drifted {offset:.2f} km from required local tile')
    return {'refreshed_url':refreshed_url,'map_center_offset_km':round(offset,4)}


def scan_one(context,query,lat,lon,diagnostics,timeout_seconds=90,max_scroll=35,
             interactive=False,verification_wait_seconds=None,zoom=16,
             force_map_refresh=False,progress=lambda msg:None,cancel_requested=lambda:False):
    """Scan one actual query. Returns a *complete* search only on verified end.

    Results with unresolved coordinates stay in the evidence for later manual
    review. A page with no proven end marker does not become a zero count.
    """
    diagnostics=Path(diagnostics);diagnostics.mkdir(parents=True,exist_ok=True)
    encoded=quote(query,safe='')
    url=f'https://www.google.com/maps/search/{encoded}/@{lat:.6f},{lon:.6f},{int(zoom)}z?hl=en'
    page=context.new_page()
    evidence={'query':query,'search_lat':lat,'search_lon':lon,'search_url':url,
              'place_links':[],'completed':False,'completion_reason':None}
    try:
        response=page.goto(url,wait_until='domcontentloaded',timeout=35000)
        code=getattr(response,'status',None)
        # Some human-verification forms themselves return HTTP 403. Let a
        # person solve those in this visible page, while hard blocks/429 fail.
        manual_403=(code==403 and interactive and any(m in
                    page.locator('body').inner_text(timeout=10000).lower()
                    for m in CHALLENGE_MARKERS))
        if code in (403,429) and not manual_403:
            evidence['failure']=f'Google Maps HTTP {code}: access temporarily restricted'
            evidence['status']='verification_required'
            _snapshot(page,diagnostics/'verification_challenge.png')
            raise HumanVerificationRequired(f'Google Maps returned HTTP {code}. This grid cell '
                                            'is incomplete and will be retried only after Resume.')
        if code and code>=500:
            raise SourceUnavailable(f'Google Maps returned HTTP {code}; grid cell preserved')
        _maybe_consent(page)
        if force_map_refresh:
            # Do not silently treat the original broad FSA text search as a
            # geofenced search. The checkbox and map URL recentering are
            # required for the 5 km Ontario competition audit.
            page.wait_for_timeout(1200)
            scope = _refresh_map_area_results(page,lat,lon)
            evidence.update(geographic_refresh_verified=True,
                            geographic_refresh_url=scope['refreshed_url'],
                            geographic_refresh_offset_km=scope['map_center_offset_km'])
        deadline=time.monotonic()+timeout_seconds
        links={}; stagnant=0; prev_length=-1; prev_height=-1
        while time.monotonic()<deadline:
            try:
                body=page.locator('body').inner_text(timeout=10000).lower()
            except Exception:body=''
            if cancel_requested():
                raise SourceUnavailable('Google Maps collection stopped; saved evidence remains')
            if any(m in body for m in CHALLENGE_MARKERS):
                evidence['status']='verification_required'
                _snapshot(page,diagnostics/'verification_challenge.png')
                if not interactive:
                    raise HumanVerificationRequired('Google Maps presented a human-verification challenge')
                progress('Google Maps verification: use this existing Firefox tab. '
                         'The current search is paused; press Stop to save and retry later.')
                until=(time.monotonic()+verification_wait_seconds
                       if verification_wait_seconds is not None else None)
                while True:
                    if cancel_requested():raise SourceUnavailable('Google verification stopped; saved evidence remains')
                    if until is not None and time.monotonic()>=until:
                        raise HumanVerificationRequired('Google Maps verification still pending; cell saved for Resume')
                    page.wait_for_timeout(2500)
                    try:body=page.locator('body').inner_text(timeout=10000).lower()
                    except Exception:continue
                    if not any(m in body for m in CHALLENGE_MARKERS):
                        # A blank intermediary page is not verification success.
                        if _page_evidence(page) or page.locator('[role="feed"]').count():break
                    if int(time.monotonic())%30<3:
                        progress('Google Maps verification is still pending in Firefox. '
                                 'Solve it there, or press Stop. Saved cells will not be lost.')
                evidence['status']='running'
                deadline=time.monotonic()+timeout_seconds
                progress('Google Maps verification cleared; continuing the SAME search')
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


def resolve_place_coordinates(context,href,timeout_ms=18000):
    """Retrieve coordinates from a Google place's canonical detail page if missing.

    Never equate a search-map centre with a business coordinate. The returned
    tuple includes the URL that proved the coordinates.
    """
    tab=context.new_page()
    try:
        tab.goto(href,wait_until='domcontentloaded',timeout=timeout_ms)
        for _ in range(5):
            candidates=[tab.url]
            for selector in ('link[rel="canonical"]','meta[property="og:url"]'):
                item=tab.locator(selector)
                if item.count():
                    value=item.first.get_attribute('href' if selector.startswith('link') else 'content')
                    if value:candidates.append(value)
            for url in candidates:
                coords=place_coordinates(url)
                if coords:return coords,url
            tab.wait_for_timeout(500)
        return None,None
    finally:
        tab.close()

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
                evidence=scan_one(context,query,lat,lon,work/job,interactive=not headless,
                                  progress=progress,cancel_requested=cancel_requested)
                cache['completed'][job]={'reason':evidence['completion_reason'],'query':query,'lat':lat,'lon':lon}
                for link in evidence['place_links']:
                    url=link['url'];coords=link['coordinates']
                    if not coords:
                        try:
                            coords,proven_url=resolve_place_coordinates(context,url)
                            if proven_url:link['coordinate_evidence_url']=proven_url
                        except Exception as exc:link['coordinate_resolution_error']=str(exc)
                    if coords:
                        la,lo=coords
                        title=link['name'] or name_from_url(url)
                        # Stable across different search grid URLs to the same
                        # place, preserving separate businesses with distinct
                        # names or locations.
                        key=f'{title.strip().casefold()}|{la:.5f}|{lo:.5f}'
                        cache['locations'][key]={'title':title,
                             'latitude':la,'longitude':lo,'link':url,'category':query,
                             'place_id':key}
                        cache['unlocated'].pop(url.split('?')[0].lower(),None)
                    else:cache['unlocated'][url.split('?')[0].lower()]=link
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
