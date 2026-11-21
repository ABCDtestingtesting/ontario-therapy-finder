"""Human-verification handling for real Street View sessions."""
import json
import pytest
from finder import housing
from finder.common import HumanVerificationRequired

class FakePage:
    def __init__(self,blocked_forever=False):
        self.blocked_forever=blocked_forever;self.nav=[];self.waits=0
    def goto(self,url,**kw):self.nav.append(url)
    def locator(self,selector):return self
    def inner_text(self,**kw):
        return 'Verify you are human' if self.blocked_forever or self.waits==0 else 'Street View'
    def wait_for_timeout(self,delay):self.waits+=1
    def screenshot(self,path,**kw):
        from pathlib import Path
        Path(path).write_bytes(b'placeholder')
class FakeContext:
    def __init__(self,page):self.pages=[page]
    def close(self):pass
class PW:
    def __enter__(self):return self
    def __exit__(self,*args):pass

def test_housing_verification_is_resolved_in_same_tab(monkeypatch,tmp_path):
    monkeypatch.setattr(housing,'DATA',tmp_path)
    monkeypatch.setattr(housing,'sync_playwright',lambda:PW())
    monkeypatch.setattr(housing,'screenshot_is_nonblank',lambda path:True)
    monkeypatch.delenv('THERAPY_UNATTENDED',raising=False)
    monkeypatch.delenv('CI',raising=False)
    page=FakePage()
    one=[{'id':'35200001','lat':43.7,'lon':-79.8}]
    result=housing.capture('L7A',one,max_usable=1,minimum_usable=1,
                     context_factory=lambda pw:FakeContext(page))
    assert len(page.nav)==1
    assert result['samples'][0]['status']=='captured_pending_review'

def test_unattended_housing_challenge_stops_not_hammers(monkeypatch,tmp_path):
    monkeypatch.setattr(housing,'DATA',tmp_path)
    monkeypatch.setattr(housing,'sync_playwright',lambda:PW())
    monkeypatch.setenv('CI','true')
    page=FakePage(blocked_forever=True)
    two=[{'id':'35200001','lat':43.7,'lon':-79.8},
         {'id':'35200002','lat':43.71,'lon':-79.81}]
    with pytest.raises(HumanVerificationRequired):
        housing.capture('L7A',two,max_usable=2,minimum_usable=1,
                    context_factory=lambda pw:FakeContext(page))
    assert len(page.nav)==1
    manifest=json.loads((tmp_path/'areas'/'L7A'/'housing'/'manifest.json').read_text())
    assert manifest['samples'][0]['status']=='verification_required'
    assert manifest['samples'][0]['point']['id']=='35200001'
