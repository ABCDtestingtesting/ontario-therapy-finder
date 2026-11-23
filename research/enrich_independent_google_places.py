"""Verify uncertain businesses found by independent zero-FSA Maps searches.

Google Maps title strings can describe career or debt counselling; only
individually retrieved Google business categories are counted as clinical
when the name does not explicitly identify psychotherapy/psychology.
All original URLs, locations and raw search observations remain intact.
"""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path

from research.enrich_google_categories import enrich
from research.verify_zero_google_coverage import summarize
from research.finalize_full_google_498 import clinical_title_classification


def run(checkpoint: Path, output: Path, seconds: int):
    data=json.loads(checkpoint.read_text())
    code=data.get('fsa')
    if not code or data.get('data_model_version')!='independent_3term_map_grid_v1':
        raise RuntimeError('Not an independent Google zero-area source')
    records=data.get('local_google_places')
    if not isinstance(records,list) or len(records)!=int(
          data.get('unique_local_google_businesses') or 0):
        raise RuntimeError('Unmatched independent observed location count')
    ids=[p.get('key') for p in records]
    if len(ids)!=len(set(ids)) or not all(ids):
        raise RuntimeError('Duplicate or absent canonical Google place IDs')
    output.parent.mkdir(parents=True,exist_ok=True)
    prepared={
        'fsa':code,
        'status':data.get('status'),
        'local_places':records,
        'unique_observed_local_places':len(records),
    }
    temp=output.parent/('category-source-'+code+'.json')
    temp.write_text(json.dumps(prepared,indent=2))
    report=None
    try:
        report=enrich(temp,max_seconds=seconds)
    finally:
        enriched=json.loads(temp.read_text())
        classified={p['key']:p for p in enriched['local_places']}
        if set(classified)!=set(ids):
            raise RuntimeError('Google business category fetch lost original place keys')
        for key,raw in data.get('observations',{}).items():
            for place in raw.get('places',[]):
                newer=classified.get(place['key'])
                if newer:
                    for field in ('google_business_category','google_category_checked_at',
                                  'google_category_evidence_url','google_category_error'):
                        if newer.get(field):
                            place[field]=newer[field]
        data['local_google_places']=list(classified.values())
        data['category_enrichment_report']=enriched.get('category_enrichment_report',report)
        summarize(data)
        output.write_text(json.dumps(data,indent=2))
    report=report or data.get('category_enrichment_report',{})
    print('INDEPENDENT_GOOGLE_CATEGORY_REVIEW',json.dumps({
        'fsa':code,'categories':report,
        'verified_clinical_place_count':data['clinical_title_confirmed'],
        'ambiguous_business_count':data['ambiguous_businesses'],
        'independent_map_queries_complete':data['status']=='all_27_independent_google_feeds_observed'}),flush=True)
    if report.get('google_access_restricted'):
        raise SystemExit('Category evidence source restricted; checkpoint preserved')
    return data


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=900)
    a=p.parse_args()
    if a.seconds<1 or a.seconds>2900:raise RuntimeError('Invalid category-check time')
    run(a.checkpoint,a.out,a.seconds)
