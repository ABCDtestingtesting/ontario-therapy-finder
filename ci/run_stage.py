"""Timeout-isolated live Mac test stage; saves one JSON record and log per stage."""
from __future__ import annotations
import argparse, datetime, json, os, signal, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'ci_results'
OUT.mkdir(parents=True,exist_ok=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('stage')
    p.add_argument('--timeout',type=int,default=900)
    args=p.parse_args()
    if args.timeout<5:raise SystemExit('Timeout must be >=5 seconds')
    cmd=[sys.executable,'-u','ci/probes.py',args.stage]
    start=time.monotonic()
    log=OUT/f'{args.stage}.log'
    rc=None;timed_out=False
    with log.open('w',encoding='utf8') as fh:
        proc=subprocess.Popen(cmd,cwd=ROOT,stdout=fh,stderr=subprocess.STDOUT,
                              start_new_session=True)
        try:rc=proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
            rc=124
    record={'stage':args.stage,'status':'passed' if rc==0 else 'failed',
            'exit_code':rc,'timed_out':timed_out,
            'duration_seconds':round(time.monotonic()-start,1),
            'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'log_file':str(log.relative_to(ROOT))}
    (OUT/f'{args.stage}.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
    print(json.dumps(record,indent=2),flush=True)
    if rc!=0:
        lines=log.read_text(encoding='utf8',errors='replace').splitlines()
        print('Last stage log lines:\n'+'\n'.join(lines[-24:]),flush=True)
    return int(rc!=0)
if __name__=='__main__':raise SystemExit(main())
