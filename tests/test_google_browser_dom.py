"""Real-browser DOM exercise with controlled Google-shaped pages, no live network."""
import shutil
import pytest
from playwright.sync_api import sync_playwright
from finder import google_browser

HTML = '''<!doctype html><html><head><title>Google Maps</title></head><body>
<div role="feed" id="feed" style="height:320px;overflow-y:auto;max-width:500px">
<a href="https://www.google.com/maps/place/Test+Clinic/data=!4m6!8m2!3d43.251!4d-79.86">Test Clinic</a>
<div style="height:1300px">More results</div><div id="end" style="display:none">You've reached the end of the list.</div>
</div><script>
var f=document.getElementById('feed');
f.addEventListener('scroll',()=>{if(f.scrollTop>200)document.getElementById('end').style.display='block'})
</script></body></html>'''


def launch(p):
    chrome=shutil.which('chromium') or shutil.which('google-chrome')
    if chrome:return p.chromium.launch(headless=True,executable_path=chrome,args=['--no-sandbox'])
    return p.firefox.launch(headless=True)


def test_actual_browser_scroll_and_list_end(tmp_path):
    with sync_playwright() as p:
        try:b=launch(p)
        except Exception as e:pytest.skip(f'No local browser available: {e}')
        try:
            ctx=b.new_context()
            class PageAdapter:
                def __init__(self,page):
                    self.real=page
                    page.set_content(HTML,wait_until='domcontentloaded')
                def goto(self,*args,**kwargs):return None
                def __getattr__(self,key):return getattr(self.real,key)
            class ContextAdapter:
                def new_page(self):return PageAdapter(ctx.new_page())
            result=google_browser.scan_one(ContextAdapter(),'psychotherapist',43.25,-79.87,tmp_path,timeout_seconds=10)
            assert result['completed']
            assert result['completion_reason']=='visible_end_of_list'
            assert len(result['place_links'])==1
            assert result['place_links'][0]['coordinates']==(43.251,-79.86)
        finally:b.close()


def test_automated_challenge_blocks_completion(tmp_path):
    challenge='<html><head><title>Google</title></head><body>Verify you are human</body></html>'
    with sync_playwright() as p:
        try:b=launch(p)
        except Exception as e:pytest.skip(f'No local browser available: {e}')
        try:
            ctx=b.new_context()
            class PageAdapter:
                def __init__(self,real):
                    self.real=real
                    real.set_content(challenge)
                def goto(self,*args,**kwargs):return None
                def __getattr__(self,key):return getattr(self.real,key)
            class ContextAdapter:
                def new_page(self):return PageAdapter(ctx.new_page())
            from finder.common import SourceUnavailable
            with pytest.raises(SourceUnavailable,match='human-verification'):
                google_browser.scan_one(ContextAdapter(),'therapist',43.25,-79.87,tmp_path,timeout_seconds=3)
            assert (tmp_path/'verification_challenge.png').exists()
            assert not __import__('json').loads((tmp_path/'search_evidence.json').read_text())['completed']
        finally:b.close()
