"""Page-by-page Psychology Today Canada directory evidence collector.

Runs in visible Firefox with one persistent profile. A verification page stays
open in that browser. Results never become an invented zero after a block.
"""
from __future__ import annotations
import re, json, time, gzip, hashlib, os
from pathlib import Path
from urllib.parse import urljoin,urlparse,parse_qs
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from .common import DATA,write_json,read_json,InvalidEvidence,SourceUnavailable
BAD=('captcha','verify you are human','unusual traffic','are you a robot','access denied',
     'checking your browser','automated traffic','just a moment','request blocked','security check')
BASE='https://www.psychologytoday.com'
PROFILE_RE=re.compile(r'/ca/therapists/[^?#/]+/([0-9]{4,12})(?:[/?#]|$)',re.I)

def blocked(html,title=''):
    soup=BeautifulSoup(html,'html.parser')
    page=(title+' '+soup.get_text(' ',strip=True)[:4000]).lower()
    return any(x in page for x in BAD)

def extract(html,fsa):
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    report=re.search(r'Number of Counsellors in\s+'+re.escape(fsa)+r'\s+([\d,]+)(\+?)',text,re.I)
    stated={'lower_bound':int(report.group(1).replace(',','')),
            'rounded':bool(report.group(2))} if report else None
    profiles={}
    for a in soup.select('a[href]'):
        href=urljoin(BASE,a.get('href',''))
        match=PROFILE_RE.search(urlparse(href).path)
        if not match:continue
        uid=match.group(1)
        # A profile can have multiple nested card links. Keep the most useful label.
        name=a.get_text(' ',strip=True)
        if not name or len(name)>200:continue
        elem=a;card=''
        for _ in range(9):
            elem=elem.parent
            if elem is None or elem.name in ('body','html','main'):break
            txt=elem.get_text(' ',strip=True)
            classes=' '.join(elem.get('class',[])).lower()
            marker=elem.name in ('article','li') or any(k in classes for k in ('card','profile','provider','result'))
            # Avoid inheriting locality labels from unrelated listing cards or
            # the directory headline in an outer page wrapper.
            contained={m.group(1) for anchor in elem.select('a[href]')
                for m in [PROFILE_RE.search(urlparse(urljoin(BASE,anchor.get('href',''))).path)] if m}
            if 30<len(txt)<2500 and (marker or (len(contained)==1 and len(txt)>=65)):
                card=txt;break
        kind='unknown'
        if card:
            if re.search(r'\bOnline Only\b',card,re.I):kind='online_only'
            elif re.search(r'\bServes Area\b',card,re.I):kind='serves_area'
            elif re.search(r'\b'+re.escape(fsa.upper())+r'\b',card,re.I):
                # A PT card that lists this FSA does not prove in-person availability.
                kind='local_postal_listing'
        old=profiles.get(uid)
        if not old or (old['kind']=='unknown' and kind!='unknown'):
            profiles[uid]={'id':uid,'name':name,'kind':kind,'url':href,'snippet':card[:600]}
    pages=set()
    for a in soup.select('a[href]'):
        href=urljoin(f'{BASE}/ca/therapists/{fsa.lower()}',a.get('href',''))
        parsed=urlparse(href)
        if not parsed.path.rstrip('/').endswith('/'+fsa.lower()):continue
        try:page=int(parse_qs(parsed.query).get('page',['-1'])[0])
        except ValueError:continue
        if 0<=page<=500:pages.add(page)
    return {'profiles':list(profiles.values()),'directory_total':stated,'page_links':sorted(pages),
            'length':len(text),'page_excerpt':text[:350]}

def collect(fsa,progress=lambda msg:None,max_pages=200,context_factory=None,cancel_requested=lambda:False):
    folder=DATA/'areas'/fsa/'pt';folder.mkdir(parents=True,exist_ok=True)
    archive=folder/'pages';archive.mkdir(exist_ok=True)
    cached=read_json(folder/'result.json',None)
    if cached and cached.get('fsa')==fsa and cached.get('unique_profiles',0)>0:
        return cached
    previous=read_json(folder/'checkpoint.json',{})
    found={p['id']:p for p in previous.get('profiles',[])}
    pages=list(previous.get('pages',[]));total=previous.get('directory_total')
    resume_index=previous.get('next_page',1)
    # A finished page checkpoint without validated result.json is incomplete.
    # Always re-fetch pages on a later run rather than getting stuck forever
    # replaying the same failed count check without visiting the website.
    end=False
    if previous.get('status')=='pages_finished':
        found={};pages=[];total=None;resume_index=1
    index=max(1,int(resume_index)) if resume_index is not None else 1
    def save(next_page,status):
        write_json(folder/'checkpoint.json',{'status':status,'next_page':next_page,
                   'profiles':list(found.values()),'directory_total':total,'pages':pages})
    if cancel_requested():
        save(index,'stopped_by_user')
        raise SourceUnavailable('Psychology Today search stopped by user; completed pages saved')
    with sync_playwright() as pw:
        profile=folder/'firefox_profile'
        context=(context_factory(pw,str(profile)) if context_factory else
                 pw.firefox.launch_persistent_context(str(profile),
                       viewport={'width':1300,'height':900},locale='en-CA',
                       headless=os.environ.get('THERAPY_HEADLESS')=='1'))
        page=context.pages[0] if context.pages else context.new_page()
        try:
            while index<=max_pages:
                if cancel_requested():
                    save(index,'stopped_by_user')
                    raise SourceUnavailable('Psychology Today search stopped by user; completed pages saved')
                target=f'{BASE}/ca/therapists/{fsa.lower()}' + (f'?page={index}' if index>1 else '')
                progress(f'{fsa}: Psychology Today page {index+1}, {len(found)} profiles saved')
                try:page.goto(target,wait_until='domcontentloaded',timeout=60000)
                except Exception as exc:
                    save(index,'retry_needed')
                    raise SourceUnavailable(f'Psychology Today navigation failed on page {index}: {exc}')
                page.wait_for_timeout(500 if os.environ.get('THERAPY_UNATTENDED')=='1' else 1800)
                # Trigger below-the-fold directory cards before parsing.
                for _scroll in range(3):
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    page.wait_for_timeout(200 if os.environ.get('THERAPY_UNATTENDED')=='1' else 450)
                raw=page.content()
                if blocked(raw,page.title()):
                    shot=folder/f'verification_{index}.png';page.screenshot(path=str(shot))
                    save(index,'waiting_for_browser_verification')
                    progress('Psychology Today verification required. Complete it in the OPEN FIREFOX WINDOW; this tab remains open.')
                    if os.environ.get('THERAPY_UNATTENDED')=='1':
                        raise SourceUnavailable('Psychology Today verification required during unattended Mac test. Diagnostic screenshot saved.')
                    # Keep same tab, recheck rather than redirecting/closing immediately.
                    waited=0
                    while blocked(page.content(),page.title()):
                        if cancel_requested():
                            save(index,'stopped_by_user')
                            raise SourceUnavailable('Psychology Today verification stopped by user; same-page checkpoint saved')
                        page.wait_for_timeout(5000);waited+=5
                        if waited%30==0:progress(f'PT browser verification still required ({waited}s). Solve it in the existing Firefox tab.')
                        if waited>=900:
                            save(index,'waiting_for_browser_verification')
                            raise SourceUnavailable('Browser verification not solved within 15 minutes. Saved current page and screenshot; restart to resume.')
                    raw=page.content()
                parsed=extract(raw,fsa)
                if not parsed['profiles']:
                    page.screenshot(path=str(folder/f'unrecognised_{index}.png'))
                    save(index,'retry_needed')
                    raise InvalidEvidence(f'Psychology Today page {index} has no recognised profile links; page screenshot retained')
                if total and parsed['directory_total'] and parsed['directory_total']!=total:
                    save(index,'retry_needed')
                    raise InvalidEvidence(f'Psychology Today displayed directory count changed between pages for {fsa}')
                if not total:total=parsed['directory_total']
                with gzip.open(archive/f'page_{index}.html.gz','wt',encoding='utf8') as fh:fh.write(raw)
                before=len(found)
                for person in parsed['profiles']:
                    old=found.get(person['id'])
                    if old is None or (old['kind']=='unknown' and person['kind']!='unknown'):
                        found[person['id']]=person
                page_rec={'page':index,'url':page.url,'profiles_on_page':len(parsed['profiles']),
                          'new_unique_profiles':len(found)-before,
                          'sha256':hashlib.sha256(raw.encode()).hexdigest()}
                pages=[x for x in pages if x['page']!=index]+[page_rec]
                next_index=index+1
                if next_index not in parsed['page_links']:
                    if any(p>next_index for p in parsed['page_links']):
                        save(index,'retry_needed')
                        raise InvalidEvidence(f'Psychology Today pagination skipped page {next_index} for {fsa}; refusing incomplete results')
                    end=True;save(None,'pages_finished');break
                save(next_index,'running');index=next_index
        finally:
            context.close()
    if not end:raise InvalidEvidence(f'Psychology Today page limit {max_pages} reached; no final page proven')
    if total is None:raise InvalidEvidence('Psychology Today total could not be read from the directory')
    if len(found)<total['lower_bound']:
        raise InvalidEvidence(f'{fsa}: {len(found)} unique PT profiles collected but directory reports at least {total["lower_bound"]}')
    classes={k:sum(x['kind']==k for x in found.values()) for k in ('local_postal_listing','online_only','serves_area','unknown')}
    evidence={'fsa':fsa,'unique_profiles':len(found),'directory_total':total,
              'classes':classes,'pages':pages,'profiles':list(found.values()),
              'source_url':f'{BASE}/ca/therapists/{fsa.lower()}',
              'uncertain_classification':classes['unknown']>0}
    write_json(folder/'result.json',evidence)
    save(None,'collected_needs_review')
    return evidence
