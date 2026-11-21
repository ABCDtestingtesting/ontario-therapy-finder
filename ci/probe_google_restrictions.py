"""Observe whether Google allows several real, consecutive geography searches.

This is a limited access diagnosis. It cannot establish success across the
thousands of searches in the full workflow, and never circumvents challenges.
"""
from __future__ import annotations
import json, os, time, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright
from finder import google_browser,census,maps
from finder.common import DATA

def main():
    folder=DATA/'ci_google_access_observation'
    folder.mkdir(parents=True,exist_ok=True)
    report={'kind':'limited_consecutive_google_test','complete_full_area':False,
            'attempts':[],'conclusion':'not_started'}
    code='L7A'
    boundaries=census.fsa_geometry(print)
    bbox=maps.bbox_with_margin(boundaries[code])
    south,west,north,east=[float(x) for x in bbox.split(',')]
    cells=list(google_browser.grid_points((south,west,north,east)))
    # Deliberately distribute positions around real search rectangle.
    chosen=[cells[min(len(cells)-1,int(i*(len(cells)-1)/11))] for i in range(12)]
    with sync_playwright() as pw:
        context=pw.firefox.launch_persistent_context(str(folder/'profile'),
            headless=True,viewport={'width':1400,'height':960},locale='en-CA')
        try:
            for i,(lat,lon) in enumerate(chosen):
                t=time.monotonic()
                row={'index':i+1,'latitude':lat,'longitude':lon,'query':'psychotherapist',
                     'status':'unverified'}
                try:
                    evidence=google_browser.scan_one(context,'psychotherapist',lat,lon,
                       folder/f'query_{i+1:02}',timeout_seconds=65,interactive=False)
                    row.update(status='completed',places=len(evidence['place_links']),
                        completed_reason=evidence['completion_reason'])
                except Exception as exc:
                    row.update(status='failed',error=type(exc).__name__+': '+str(exc))
                    report['conclusion']='access_or_completion_failure_at_query_'+str(i+1)
                row['seconds']=round(time.monotonic()-t,1)
                report['attempts'].append(row)
                print('OBSERVATION',json.dumps(row),flush=True)
                with (folder/'report.json').open('w') as f:json.dump(report,f,indent=2)
                if row['status']!='completed':break
            else:
                report['conclusion']='12_queries_completed_but_full_area_unproven'
        finally:context.close()
    with (folder/'report.json').open('w') as f:json.dump(report,f,indent=2)
    print('FULL-AREA COVERAGE NOT PROVEN',json.dumps(report),flush=True)

if __name__=='__main__':main()
