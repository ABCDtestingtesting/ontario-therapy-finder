"""Crash-resistant durable research queue and explicit stage audit."""
from __future__ import annotations
import threading, copy, traceback
from .common import DATA,LOGS,read_json,write_json,utc,Incomplete
FILE=DATA/'run_state.json';MUTEX=threading.RLock()
STAGES=('population','google','psychology_today','housing')

def read():
    with MUTEX:
        d=read_json(FILE,{'job':{'status':'idle','message':'Ready'},'areas':{},'events':[],'census':{}})
        return copy.deepcopy(d)
def edit(fn):
    with MUTEX:
        d=read_json(FILE,{'job':{'status':'idle','message':'Ready'},'areas':{},'events':[],'census':{}})
        fn(d)
        write_json(FILE,d)
        return copy.deepcopy(d)
def event(message):
    def f(d):
        d.setdefault('events',[]).append({'at':utc(),'message':str(message)[:800]})
        d['events']=d['events'][-150:]
    edit(f)
def job(status,message,**kw):
    def f(d):d['job']={'status':status,'message':str(message),'updated':utc(),**kw}
    edit(f)
def progress(message,**kw):
    # Keep the stable operation label so the browser always reports progress
    # beside the control which started the job. Do not overwrite job.message.
    def f(d):d.setdefault('job',{}).update(progress=str(message),updated=utc(),**kw)
    edit(f)
def stage(fsa,source,status,evidence=None,error=None):
    if source not in STAGES:raise ValueError(source)
    def f(d):
        d.setdefault('areas',{}).setdefault(fsa,{})[source]={
            'status':status,'evidence':evidence,'error':str(error) if error else None,
            'at':utc()}
    edit(f)
def mark_interrupted_jobs():
    def f(d):
        if d.get('job',{}).get('status')=='running':
            d['job']['status']='interrupted'
            d['job']['message']='Previous run stopped. All saved work is retained; press Resume.'
        for a in d.get('areas',{}).values():
            for s in a.values():
                if isinstance(s,dict) and s.get('status')=='running':s['status']='interrupted'
    edit(f)
def require_complete(fsas, sources=STAGES):
    state=read();bad=[]
    for code in fsas:
        for s in sources:
            row=state['areas'].get(code,{}).get(s,{})
            if row.get('status')!='verified':
                bad.append(f"{code}/{s}: {row.get('status','not_started')}: {row.get('error') or 'not confirmed'}")
    if bad:raise Incomplete('Cannot generate a complete ranking. Incomplete: '+'; '.join(bad[:20]))
    return state
