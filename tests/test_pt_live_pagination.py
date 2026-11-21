"""Regression for Psychology Today's real 1-based ?page=2,3,4 links.

The actual L7A directory begins at /ca/therapists/l7a, then /ca/therapists/l7a?page=2.
Older V5 fixtures had ?page=1 and silently stopped after page 1.
"""
import pytest
from finder import psychology_today as pt
from finder.common import InvalidEvidence

class Browser:
    def __init__(self, contents):
        self.contents=contents;self.urls=[];self.html='';self.url=''
    def goto(self, url, **kwargs):
        self.urls.append(url);self.url=url
        number=int(url.split('?page=')[1]) if '?page=' in url else 1
        self.html=self.contents[number]
    def wait_for_timeout(self, _):pass
    def evaluate(self, _):pass
    def content(self):return self.html
    def title(self):return 'Therapists in L7A'
    def screenshot(self,path):raise AssertionError('Unexpected screenshot')
class Context:
    def __init__(self,browser):self.pages=[browser]
    def close(self):pass
class PW:
    def __enter__(self):return self
    def __exit__(self,*args):return False

def directory(page, links, unique_id):
    anchors=''.join(f'<a href="?page={i}">{i}</a>' for i in links)
    return f'''<html><body><h1>Therapists in L7A</h1>
    <section class="card"><div>Brampton, ON L7A</div><p>Adult psychotherapy practice</p>
    <a href="/ca/therapists/test-practitioner-brampton-on/{unique_id}">Practitioner {unique_id}</a></section>
    {anchors}<h3>Number of Counsellors in L7A</h3><p>3+</p></body></html>'''

def test_four_page_live_pagination_complete(monkeypatch,tmp_path):
    monkeypatch.setattr(pt,'DATA',tmp_path)
    monkeypatch.setattr(pt,'sync_playwright',lambda:PW())
    pages={1:directory(1,[2,3,4],'10001'),2:directory(2,[1,3,4],'10002'),
           3:directory(3,[2,4],'10003'),4:directory(4,[3],'10004')}
    browser=Browser(pages)
    report=pt.collect('L7A',context_factory=lambda *args:Context(browser))
    assert browser.urls==[
        'https://www.psychologytoday.com/ca/therapists/l7a',
        'https://www.psychologytoday.com/ca/therapists/l7a?page=2',
        'https://www.psychologytoday.com/ca/therapists/l7a?page=3',
        'https://www.psychologytoday.com/ca/therapists/l7a?page=4']
    assert report['unique_profiles']==4
    assert len(report['pages'])==4

def test_missing_page_in_pagination_is_failure(monkeypatch,tmp_path):
    monkeypatch.setattr(pt,'DATA',tmp_path)
    monkeypatch.setattr(pt,'sync_playwright',lambda:PW())
    browser=Browser({1:directory(1,[3,4],'10001')})
    with pytest.raises(InvalidEvidence,match='skipped page 2'):
        pt.collect('L7A',context_factory=lambda *args:Context(browser))
    assert len(browser.urls)==1
    checkpoint=pt.read_json(tmp_path/'areas'/'L7A'/'pt'/'checkpoint.json')
    assert checkpoint['status']=='retry_needed'
