"""Generate evidence-discovery worklists; no automated site access."""
import argparse,csv,json,re
from urllib.parse import urlencode
ENGINES={
 'google':('https://www.google.ca/search?',{'gl':'ca','hl':'en'}),
 'bing':('https://www.bing.com/search?',{'cc':'ca','setlang':'en'}),
 'duckduckgo':('https://duckduckgo.com/?',{'kl':'ca-en'}),
 'brave':('https://search.brave.com/search?',{'country':'ca'})
}
def plan(rows,localities):
 assert len(rows)==60 and len({r['fsa'] for r in rows})==60
 for r in rows:
  f=r['fsa']
  assert re.fullmatch(r'[A-Z][0-9][A-Z]',f)
  variants={
   'exact':f'"{f}" therapist Ontario site:psychologytoday.com/ca/therapists/',
   'online':f'"{f}" "online" site:psychologytoday.com/ca/therapists/',
   'additional':f'"{f}" "additional location" site:psychologytoday.com/ca/therapists/',
   'directory':f'"{f}" Psychology Today therapists Ontario'
  }
  for i,city in enumerate(localities.get(f,[])):
   variants[f'locality_{i}']=f'"{f}" "{city}" site:psychologytoday.com/ca/therapists/'
  for engine,(base,options) in ENGINES.items():
   for variant,q in variants.items():
    yield dict(fsa=f,source=engine,variant=variant,query=q,url=base+urlencode(dict(options,q=q)),scope='indexed_discovery',authorization_required=False)
  for variant,suffix in [('unfiltered',''),('adults','?category=adults'),('in_person','?category=in-person')]:
   yield dict(fsa=f,source='pt',variant=variant,url='https://www.psychologytoday.com/ca/therapists/'+f.lower()+suffix,scope='direct_directory',authorization_required=True)
if __name__=='__main__':
 p=argparse.ArgumentParser()
 p.add_argument('--baseline',default='research/pt_candidates_2026-11-24.csv')
 p.add_argument('--localities',help='JSON mapping FSA to verified municipality/neighbourhood names')
 p.add_argument('--out',required=True)
 a=p.parse_args()
 with open(a.baseline,newline='') as f: rows=list(csv.DictReader(f))
 loc={}
 if a.localities:
  with open(a.localities) as f: loc=json.load(f)
 out=list(plan(rows,loc))
 with open(a.out,'w') as f: json.dump(out,f,indent=2)
 print(len(out),'search tasks')
