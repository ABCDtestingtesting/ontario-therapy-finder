import pytest
from pathlib import Path
from PIL import Image
from shapely.geometry import mapping,box
from finder import psychology_today as pt,housing
from finder.common import InvalidEvidence

def card(id,name,tag,code='L7A'):
    return f'<div class="card"><span>{tag} {code}</span><p>Clinical psychology and individual therapy for adults</p><a href="/ca/therapists/{name.lower()}/{id}">{name}</a></div>'

def pt_page(cards,links='',count='2+'):
    return f'<html><body><h2>Number of Counsellors in L7A {count}</h2>{cards}{links}</body></html>'

def test_pt_profile_classification_and_pagination():
    html=pt_page(card('12345','Alice','Online Only')+card('12346','Bob','Serves Area'),'<a href="?page=2">Next</a>')
    x=pt.extract(html,'L7A')
    assert x['directory_total']=={'lower_bound':2,'rounded':True}
    assert sorted(p['kind'] for p in x['profiles'])==['online_only','serves_area']
    assert x['page_links']==[2]

def test_pt_unknown_not_silent():
    html=pt_page('<a href="/ca/therapists/unknown/12345">Alice</a>')
    assert pt.extract(html,'L7A')['profiles'][0]['kind']=='unknown'

def test_pt_bad_page_detection():
    assert pt.blocked('<html><body>Verify you are human - CAPTCHA</body></html>')
    assert not pt.blocked(pt_page(card('12345','Alice','Serves Area')))

def test_streetview_uses_free_maps_urls():
    u=housing.street_url(43.25,-79.88,90)
    assert u.startswith('https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=43.250000')

def test_housing_sampling_spreads_points():
    fsa=mapping(box(-79.9,43.2,-79.87,43.24))
    da={f'3520000{i}':mapping(box(-79.9+i*.005,43.2,-79.896+i*.005,43.21)) for i in range(1,6)}
    pop={id:{'occupied':100,'population':300} for id in da}
    result=housing.sample_points(fsa,da,pop,limit=10,min_gap=0)
    assert len(result)==5 and all(fsa is not None for _ in result)

def test_screenshot_image_validation(tmp_path):
    p=tmp_path/'image.png'
    Image.new('RGB',(1365,880),'white').save(p)
    assert not housing.screenshot_is_nonblank(p)
    im=Image.new('RGB',(1365,880));pix=im.load()
    for x in range(im.width):
        for y in range(im.height):pix[x,y]=(x%256,y%256,(x+y)%256)
    im.save(p)
    assert housing.screenshot_is_nonblank(p)

def test_manual_review_requires_actual_captured_photo(monkeypatch,tmp_path):
    from finder.common import write_json
    monkeypatch.setattr(housing,'DATA',tmp_path)
    folder=tmp_path/'areas'/'L7A'/'housing';folder.mkdir(parents=True)
    image=folder/'real.png';Image.new('RGB',(1365,880),'white').save(image)
    write_json(folder/'manifest.json',{'samples':[{'point':{'id':'35200001'},'status':'captured_pending_review','image':str(image)}]})
    with pytest.raises(InvalidEvidence):housing.mark_review('L7A','35200001','detached','short')
    d=housing.mark_review('L7A','35200001','detached','I can see detached houses.')
    assert d['human_review']['category']=='detached'

def test_reviewed_count_not_fooled_by_screenshots():
    evidence={'samples':[{'status':'captured_pending_review','image':'x'},
                         {'status':'captured_pending_review','human_review':{'category':'townhouse'}}]}
    assert housing.count_reviewed(evidence)==1

class StubPage:
    def __init__(self,pages,fail_on=None):
        self.pages=pages;self.fail_on=fail_on;self.visited=[];self.url='';self.html=''
    def goto(self,url,**kw):
        self.visited.append(url);self.url=url
        index=int(url.split('?page=')[-1]) if '?page=' in url else 1
        if index==self.fail_on:raise RuntimeError('Injected website failure')
        self.html=self.pages[index-1]
    def wait_for_timeout(self,millis):pass
    def evaluate(self,js):pass
    def content(self):return self.html
    def title(self):return 'Therapists in L7A'
    def screenshot(self,path):Path(path).write_bytes(b'diagnostic screenshot')

class StubContext:
    def __init__(self,page):self.pages=[page];self.closed=False
    def close(self):self.closed=True

class StubPlaywright:
    def __enter__(self):return self
    def __exit__(self,*args):return False

def test_real_collector_loop_page_pagination_caches_success(tmp_path,monkeypatch):
    monkeypatch.setattr(pt,'DATA',tmp_path)
    monkeypatch.setattr(pt,'sync_playwright',lambda:StubPlaywright())
    page=StubPage([pt_page(card('12345','Alice','Online Only'),'<a href="?page=2">Next</a>',count='2'),
                   pt_page(card('12346','Bob','Serves Area'),count='2')])
    context=StubContext(page)
    result=pt.collect('L7A',context_factory=lambda pw,profile:context)
    assert result['unique_profiles']==2 and result['classes']['online_only']==1
    assert len(page.visited)==2 and context.closed
    assert (tmp_path/'areas'/'L7A'/'pt'/'pages'/'page_1.html.gz').exists()
    cached=pt.collect('L7A',context_factory=lambda pw,profile: (_ for _ in ()).throw(AssertionError('cache must be reused')))
    assert cached['unique_profiles']==2

def test_collector_resume_after_navigation_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(pt,'DATA',tmp_path)
    monkeypatch.setattr(pt,'sync_playwright',lambda:StubPlaywright())
    documents=[pt_page(card('12345','Alice','Online Only'),'<a href="?page=2">Next</a>',count='2'),
               pt_page(card('12346','Bob','Serves Area'),count='2')]
    first=StubPage(documents,fail_on=2)
    with pytest.raises(pt.SourceUnavailable):
        pt.collect('L7A',context_factory=lambda *args:StubContext(first))
    checkpoint=pt.read_json(tmp_path/'areas'/'L7A'/'pt'/'checkpoint.json')
    assert checkpoint['next_page']==2 and checkpoint['status']=='retry_needed'
    second=StubPage(documents)
    result=pt.collect('L7A',context_factory=lambda *args:StubContext(second))
    assert len(second.visited)==1 and second.visited[0].endswith('?page=2')
    assert result['unique_profiles']==2

def test_verified_housing_context_is_geographic():
    report={'samples':[{'status':'captured_pending_review','point':{'id':'A','lat':43.2,'lon':-79.9},
                        'human_review':{'category':'detached'},'url':'https://maps.google.com/1'},
                       {'status':'captured_pending_review','point':{'id':'B','lat':43.6,'lon':-79.9},
                        'human_review':{'category':'townhouse'},'url':'https://maps.google.com/2'},
                       {'status':'captured_pending_review','point':{'id':'C','lat':43.2,'lon':-79.9},
                        'human_review':{'category':'unknown'},'url':'https://maps.google.com/3'}]}
    r=housing.contextual_housing(report,43.2,-79.9)
    assert r['photos']==1 and r['observed_types']=={'detached':1}
