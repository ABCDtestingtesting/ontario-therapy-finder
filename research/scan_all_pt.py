"""Live weekly Psychology Today advertised FSA therapist count, sharded."""
import argparse,json,re,time,traceback
from html.parser import HTMLParser
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

class VisibleText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.off=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.off+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript'):self.off=max(0,self.off-1)
    def handle_data(self,data):
        if not self.off:self.parts.append(data)

def main():
    p=argparse.ArgumentParser();p.add_argument('--shard',type=int,required=True);p.add_argument('--shards',type=int,default=10)
    a=p.parse_args()
    pool=json.loads(Path('research/ontario_401_fsa_2021.json').read_text())['areas']
    pool=[x for i,x in enumerate(pool) if i%a.shards==a.shard]
    out=Path('pt-output')/f'shard-{a.shard:02d}';out.mkdir(parents=True,exist_ok=True)
    results=[]
    for rec in pool:
        code=rec['fsa'];url=f'https://www.psychologytoday.com/ca/therapists/{code.lower()}'
        item={'fsa':code,'url':url,'status':'unknown','checked_at_utc':datetime.now(timezone.utc).isoformat()}
        try:
            req=Request(url,headers={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 13.0; rv:129.0) Gecko/20100101 Firefox/129.0',
                 'Accept':'text/html,application/xhtml+xml','Accept-Language':'en-CA,en;q=0.8'})
            with urlopen(req,timeout=26) as response:
                raw=response.read(2500000).decode('utf-8','replace')
                item['http_status']=response.status
                item['final_url']=response.url
            v=VisibleText();v.feed(raw)
            visible=re.sub(r'\s+',' ',' '.join(v.parts))
            match=re.search(r'Number\s+of\s+Counsellors\s+in\s+'+re.escape(code)+r'\s*(<\s*10|[\d,]+\s*\+?)',visible,re.I)
            if match and item['final_url'].rstrip('/')==url.rstrip('/'):
                text=match.group(1).strip()
                item['display']=text;item['status']='observed'
                if '<' in text:
                    item['lower_bound']=0;item['upper_bound_exclusive']=10
                else:
                    item['lower_bound']=int(re.sub(r'\D','',text));item['rounded']=text.endswith('+')
            else:item['reason']='Expected directory and formatted count not found'
        except HTTPError as e:
            item['http_status']=e.code;item['status']='blocked' if e.code in (403,429) else 'unknown'
            item['reason']=str(e)
        except Exception as e:item['reason']=repr(e)[:300]
        results.append(item)
        (out/'results.json').write_text(json.dumps({'shard':a.shard,'expected':len(pool),'completed':len(results),'rows':results},indent=2))
        print('LIVE_PT',json.dumps(item),flush=True)
        if item['status']=='blocked':
            print('PT restriction; stopping this shard',flush=True)
            break
        time.sleep(0.7)
    print('PT_SHARD_FINISHED',a.shard,len(results),'of',len(pool),flush=True)
if __name__=='__main__':main()
