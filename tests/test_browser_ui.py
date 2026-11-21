"""Browser page interactions (Chromium on Linux, Firefox on Mac), simulated
network responses because the
container blocks browser navigation to localhost (ERR_BLOCKED_BY_ADMINISTRATOR).
The separately tested FastAPI endpoints cover the actual server protocol.
"""
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from finder.common import ROOT

@pytest.fixture
def page():
    exe=Path('/usr/bin/chromium')
    html=(ROOT/'web'/'index.html').read_text()
    with sync_playwright() as pw:
        if exe.exists():
            b=pw.chromium.launch(headless=True,executable_path=str(exe),args=['--no-sandbox'])
        else:
            # start.command installs Playwright Firefox on macOS.
            b=pw.firefox.launch(headless=True)
        pg=b.new_page(viewport={'width':1440,'height':900})
        pg.route('https://unpkg.com/**',lambda route:route.abort())
        pg.goto('about:blank')
        pg.evaluate('''() => {
         window.__requests=[];
         window.fetch=async function(u,opt){
          let url=String(u);window.__requests.push(url);
          let status=200,body={};
          if(url.startsWith('/api/status')){
           body={ok:true,version:'4.0.0',busy:false,google_engine_installed:false,
              census:{fsa_population:false,da_population:false,fsa_boundaries:false,ready:false},
              state:{job:{status:'idle',message:'Ready'},areas:{},events:[]}};
          }else if(url.startsWith('/api/census')){
           // Deliberately omit "ok" to reproduce the user's earlier HTTP 200 bug.
           body={message:'Census request accepted (HTTP 200 without ok)'};
          }else if(url.startsWith('/api/eligible')){
           status=409;body={ok:false,error:'Census data are missing. Complete the first step.'};
          }else if(url.startsWith('/api/run')){
           status=409;body={ok:false,error:'Complete official census data setup before searching'};
          }else if(url.startsWith('/api/rank')){
           status=409;body={ok:false,error:'Cannot generate a complete ranking. Incomplete evidence.'};
          }else if(url.startsWith('/api/stop')){
           body={ok:true,message:'Stop requested'};
          }else if(url.startsWith('/api/evidence')){
           status=404;body={ok:false,error:'No evidence for this stage yet'};
          }else if(url.startsWith('/api/approve')){
           status=409;body={ok:false,error:'No source awaiting review'};
          }
          return {ok:status>=200&&status<300,status:status,json:async()=>body};
         }
        }''')
        pg.set_content(html,wait_until='domcontentloaded')
        yield pg
        b.close()

def test_actual_page_buttons_and_dashboard_health(page):
    assert 'Ontario Therapy Area Research' in page.locator('h1').inner_text()
    page.wait_for_function("document.querySelector('#version').textContent.includes('4.0.0')",timeout=6000)
    assert page.get_by_role('button',name='Download and validate census data').is_visible()
    assert page.get_by_role('button',name='Show eligible areas').is_visible()
    assert page.get_by_role('button',name='Run / resume all four sources').is_visible()
    page.screenshot(path=str(ROOT/'docs'/'browser_dashboard_test.png'),full_page=True)

def test_eligible_click_reports_missing_data_next_to_button(page):
    page.locator('#eligibleButton').click()
    page.locator('#eligibleFeedback.bad').wait_for(timeout=3000)
    assert 'Census data are missing' in page.locator('#eligibleFeedback').inner_text()

def test_run_and_rank_buttons_report_real_errors_without_scrolling(page):
    page.locator('#runButton').click()
    page.locator('#runFeedback.bad').wait_for(timeout=3000)
    assert 'census' in page.locator('#runFeedback').inner_text().lower()
    page.locator('#rankButton').click()
    page.locator('#rankFeedback.bad').wait_for(timeout=3000)
    assert 'incomplete' in page.locator('#rankFeedback').inner_text().lower()

def test_http200_with_no_ok_does_not_claim_service_unavailable(page):
    page.locator('#censusButton').click()
    page.wait_for_function("document.querySelector('#censusFeedback').textContent.includes('Census request accepted')",timeout=3000)
    txt=page.locator('#censusFeedback').inner_text()
    assert 'HTTP 200' in txt and 'Service unavailable' not in txt

def test_approve_and_evidence_buttons_show_errors(page):
    page.locator('#inspectButton').click()
    page.locator('#reviewFeedback.bad').wait_for(timeout=3000)
    assert 'No evidence' in page.locator('#reviewFeedback').inner_text()
    page.locator('#note').fill('I verified the source listings and clinical locations.')
    page.locator('#approveButton').click()
    page.wait_for_function("document.querySelector('#reviewFeedback').textContent.includes('No source awaiting review')",timeout=3000)
