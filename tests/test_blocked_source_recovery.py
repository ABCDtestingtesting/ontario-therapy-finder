"""Provider blocking must preserve evidence, permit manual recovery and stop hammering."""
from pathlib import Path
import pytest
from shapely.geometry import box, mapping
from finder import google_browser, psychology_today as pt, maps, server, state
from finder.common import HumanVerificationRequired, SourceUnavailable, Incomplete


class PTPage:
    def __init__(self, page, status=None, resolve_after=None):
        self.html='Verify you are human (captcha)'
        self.good=page
        self.status=status;self.resolve_after=resolve_after
        self.waits=0;self.urls=[];self.url=''
    def goto(self, url, **kw):
        self.urls.append(url);self.url=url
        return type('Response', (), {'status':self.status})() if self.status is not None else None
    def wait_for_timeout(self, ms):
        self.waits+=1
        if self.resolve_after is not None and self.waits>=self.resolve_after:
            self.html=self.good
    def evaluate(self, js):pass
    def content(self):return '<html><body>'+self.html+'</body></html>'
    def title(self):return 'Verification'
    def screenshot(self,path):Path(path).write_bytes(b'challenge screenshot')
class PTContext:
    def __init__(self,page):self.pages=[page];self.closed=False
    def close(self):self.closed=True
class PW:
    def __enter__(self):return self
    def __exit__(self,*args):return False

GOOD='''<h2>Number of Counsellors in L7A 1+</h2>
<section class="card"><span>Hamilton ON L7A</span><p>Adult psychotherapy clinic</p>
<a href="/ca/therapists/some-therapist/12345">Some Therapist</a></section>'''

def test_pt_manual_verification_resumes_same_tab(tmp_path,monkeypatch):
    monkeypatch.setattr(pt,'DATA',tmp_path)
    monkeypatch.setattr(pt,'sync_playwright',lambda:PW())
    monkeypatch.delenv('CI',raising=False)
    monkeypatch.delenv('THERAPY_UNATTENDED',raising=False)
    pg=PTPage(GOOD,resolve_after=8);ctx=PTContext(pg)
    result=pt.collect('L7A',context_factory=lambda *args:ctx)
    assert len(pg.urls)==1 and result['unique_profiles']==1
    assert ctx.closed and (tmp_path/'areas'/'L7A'/'pt'/'verification_1.png').exists()
    assert pt.read_json(tmp_path/'areas'/'L7A'/'pt'/'checkpoint.json')['status']=='collected_needs_review'


def test_pt_manual_block_can_be_stopped_and_resumed(tmp_path,monkeypatch):
    monkeypatch.setattr(pt,'DATA',tmp_path)
    monkeypatch.setattr(pt,'sync_playwright',lambda:PW())
    monkeypatch.delenv('CI',raising=False)
    monkeypatch.delenv('THERAPY_UNATTENDED',raising=False)
    pg=PTPage(GOOD);ctx=PTContext(pg)
    with pytest.raises(SourceUnavailable,match='stopped by user'):
        pt.collect('L7A',context_factory=lambda *args:ctx,cancel_requested=lambda:pg.waits>=8)
    cp=pt.read_json(tmp_path/'areas'/'L7A'/'pt'/'checkpoint.json')
    assert cp['status']=='stopped_by_user' and cp['next_page']==1
    assert ctx.closed
    pg2=PTPage(GOOD,resolve_after=6)
    result=pt.collect('L7A',context_factory=lambda *args:PTContext(pg2))
    assert result['unique_profiles']==1


def test_pt_http429_marks_incomplete_and_no_loop(tmp_path,monkeypatch):
    monkeypatch.setattr(pt,'DATA',tmp_path)
    monkeypatch.setattr(pt,'sync_playwright',lambda:PW())
    pg=PTPage(GOOD,status=429)
    with pytest.raises(HumanVerificationRequired,match='429'):
        pt.collect('L7A',context_factory=lambda *args:PTContext(pg))
    cp=pt.read_json(tmp_path/'areas'/'L7A'/'pt'/'checkpoint.json')
    assert cp['status']=='verification_required' and cp['next_page']==1
    assert not (tmp_path/'areas'/'L7A'/'pt'/'result.json').exists()


class GooglePage:
    def __init__(self, resolve=True, http=None):
        self.waits=0;self.resolve=resolve;self.http=http;self.url=''
        self.closed=False
    def goto(self,url,**kw):
        self.url=url
        return type('Response', (), {'status':self.http})() if self.http else None
    def title(self):return 'Maps results'
    def screenshot(self,path,**kw):Path(path).write_bytes(b'challenge screenshot')
    def close(self):self.closed=True
    def _ready(self):return self.resolve and self.waits>=2
    def wait_for_timeout(self,ms):self.waits+=1
    def locator(self,selector):
        pg=self
        class Loc:
            def inner_text(self,**kw):return 'You\'ve reached the end of the list' if pg._ready() else 'Verify you are human'
            def count(self):return 1 if pg._ready() else 0
            def evaluate(self,js):return {'height':1,'top':0,'client':1}
        return Loc()
    def eval_on_selector_all(self,sel,expr):
        if self._ready():
            return [{'href':'https://www.google.com/maps/place/Test/data=!3d43.25!4d-79.87','text':'Test'}]
        return []
class GoogleContext:
    def __init__(self,page):self.page=page
    def new_page(self):return self.page


def test_google_verification_resumes_same_tab_and_checks_real_links(tmp_path):
    pg=GooglePage()
    out=google_browser.scan_one(GoogleContext(pg),'therapist',43.25,-79.87,tmp_path,
                                 interactive=True,verification_wait_seconds=20)
    assert out['completed'] and len(out['place_links'])==1 and pg.closed
    assert (tmp_path/'verification_challenge.png').exists()


def test_google_429_remains_incomplete(tmp_path):
    pg=GooglePage(http=429)
    with pytest.raises(HumanVerificationRequired,match='429'):
        google_browser.scan_one(GoogleContext(pg),'therapist',43.25,-79.87,tmp_path,interactive=True)
    ev=google_browser.read_json(tmp_path/'search_evidence.json')
    assert ev['status']=='verification_required' and not ev['completed']


def test_maps_does_not_switch_scrapers_when_blocked(tmp_path,monkeypatch):
    monkeypatch.setattr(maps,'DATA',tmp_path)
    monkeypatch.delenv('THERAPY_NATIVE_MAPS_FIRST',raising=False)
    monkeypatch.setattr(google_browser,'collect',lambda *a,**kw: (_ for _ in ()).throw(HumanVerificationRequired('blocked')))
    monkeypatch.setattr(maps,'ensure_binary',lambda *a: (_ for _ in ()).throw(AssertionError('must not launch native scraper')))
    with pytest.raises(HumanVerificationRequired,match='blocked'):
        maps.execute('L7A',mapping(box(-79.85,43.68,-79.82,43.71)))
    assert not (tmp_path/'areas'/'L7A'/'google'/'locations.json').exists()


def test_bulk_scan_defers_blocked_provider_no_fake_zeros(tmp_path,monkeypatch):
    monkeypatch.setattr(server.census,'fsa_geometry',lambda:{'L7A':mapping(box(-79.9,43.7,-79.8,43.8)),
                                                          'L6Z':mapping(box(-79.9,43.7,-79.8,43.8))})
    monkeypatch.setattr(state,'FILE',tmp_path/'state.json')
    calls=[]
    monkeypatch.setattr(server,'do_population',lambda f,g:state.stage(f,'population','verified',{}))
    monkeypatch.setattr(server,'do_housing',lambda f,g,a:state.stage(f,'housing','verified',{}))
    monkeypatch.setattr(server,'do_pt',lambda f:state.stage(f,'psychology_today','verified',{}))
    def block(f,g):calls.append(f);raise HumanVerificationRequired('Google blocked searches')
    monkeypatch.setattr(server,'do_google',block)
    blocked=set()
    assert server.process_area('L7A',blocked_sources=blocked)
    assert server.process_area('L6Z',blocked_sources=blocked)
    assert calls==['L7A'] and blocked=={'google'}
    assert state.read()['areas']['L6Z']['google']['status']=='verification_required'
    with pytest.raises(Incomplete):state.require_complete(['L7A','L6Z'])
