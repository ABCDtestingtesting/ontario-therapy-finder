"""Fail the CI job if ANY required live Mac test is missing or failed."""
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'ci_results'
REQUIRED=('app','mac_launcher','census','maps','psychology_today','housing_capture')
def produce():
    lines=['# Mac live test results','','These checks run on hosted macOS; they are real external requests.','Passing them does not prove exhaustive directory coverage or all-Mac compatibility.','']
    failed=[]
    for stage in REQUIRED:
        record=OUT/f'{stage}.json'
        try:data=json.loads(record.read_text(encoding='utf8'))
        except (FileNotFoundError,ValueError):
            data={'status':'missing','exit_code':'N/A'}
        status=data.get('status')
        lines.append(f'- {stage}: {status} (exit: {data.get("exit_code")}, duration: {data.get("duration_seconds", "unknown")}s)')
        if status!='passed':failed.append(stage)
    lines.extend(['', 'Result: '+('FAILED — '+', '.join(failed) if failed else 'ALL SIX PROBES PASSED'),
                  '', 'Housing screenshot capture requires separate verification of visible housing.',
                  'Complete Ontario scan and final ranking have not been certified by these bounded probes.'])
    result='\n'.join(lines)+'\n'
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/'SUMMARY.md').write_text(result,encoding='utf8')
    print(result,flush=True)
    return failed
if __name__=='__main__':sys.exit(1 if produce() else 0)
