"""Conservatively merge fresh Google Maps 18-tile FSA evidence into the
full 498-area five-kilometre clinical competition source ledger.
"""
from __future__ import annotations
import argparse,csv,json,math
from datetime import datetime,timezone
from fractions import Fraction
from pathlib import Path
from research.finalize_full_google_498 import clinical_title_classification, recovery_geographically_verified
from research.scan_all_maps import distance_km

OFFSETS=(-3.4,0.0,3.4)
TERMS=('psychotherapist','psychologist')
TILE_KEYS={'map_movement_v7_checkbox_on|'+'|'.join(map(str,(n,e,0,term)))
    for n in OFFSETS for e in OFFSETS for term in TERMS}

def verify_doc(code,doc,center):
    if doc.get('fsa')!=code or len(TILE_KEYS)!=18:
        raise RuntimeError('Wrong FSA checkpoint or map query plan')
    found=doc.get('center')
    if not isinstance(found,(list,tuple)) or len(found)!=2 or any(
        abs(float(a)-float(b))>0.00001 for a,b in zip(found,center)):
        raise RuntimeError('Google source center does not match 2021 FSA')
    tiles=doc.get('complete_tiles',{})
    complete=(doc.get('status')=='verified_tile_feed'
        and int(doc.get('completed_coverage_tiles',0))==18
        and int(doc.get('total_coverage_tiles',0))==18
        and not doc.get('pending')
        and not doc.get('source_caps_present')
        and int(doc.get('capped_leaf_tiles',0))==0
        and int(doc.get('unresolved_leaf_links',0))==0
        and TILE_KEYS.issubset(set(tiles))
        and recovery_geographically_verified(doc)
        and all(tiles[k].get('status')=='observed'
          and tiles[k].get('map_area_search_verified') is True
          and tiles[k].get('capped') is False
          and not tiles[k].get('unresolved')
          for k in TILE_KEYS))
    places=doc.get('local_places') or []
    if len(places)!=int(doc.get('unique_observed_local_places',-1)):
        raise RuntimeError('Saved FSA place count mismatch '+code)
    if len({p['key'] for p in places})!=len(places):
        raise RuntimeError('Duplicated Google business in '+code)
    classifications=[]
    for p in places:
        if not str(p.get('key','')).strip() or not str(p.get('name','')).strip():
            raise RuntimeError('Business without mapped name or key '+code)
        if not str(p.get('source_url','')).startswith('https://www.google.com/maps/place/'):
            raise RuntimeError('Google place detail provenance missing '+code)
        try:
            coords=(float(p['lat']),float(p['lon']))
            if (not all(math.isfinite(v) for v in coords) or distance_km(center,coords)>5.001):
                raise RuntimeError('Mapped Google clinic outside five-kilometre FSA study '+code)
        except (TypeError,ValueError,KeyError) as exc:
            raise RuntimeError('Google clinic missing verified geographical coordinates '+code) from exc
        checked=dict(p)
        if checked.get('google_business_category') and not (
            str(checked.get('google_category_evidence_url','')).startswith('https://www.google.com/maps/place/')
            and checked.get('google_category_checked_at')):
            checked.pop('google_business_category',None)
        classifications.append(clinical_title_classification(checked))
    clinical=classifications.count('clinical')
    ambiguous=classifications.count('ambiguous')
    verified_clinical_complete=complete and ambiguous==0
    return clinical,ambiguous,verified_clinical_complete,complete

def merge(source,checkpoints,out):
    with Path(source).open(newline='',encoding='utf8') as fh:
        rows=list(csv.DictReader(fh))
    if len(rows)!=498 or len({r['fsa'] for r in rows})!=498:
        raise RuntimeError('498 FSA audit must be complete')
    by_code={r['fsa']:r for r in rows}
    sources={}
    for path in Path(checkpoints).glob('**/[A-Z][0-9][A-Z].json'):
        code=path.stem
        if code not in by_code or code in sources:
            raise RuntimeError('Unknown or duplicated new Google source '+code)
        sources[code]=json.loads(path.read_text())
    if not sources:raise RuntimeError('No recovered source checkpoints')
    changed=0
    new_total=0
    completed=0
    unfinished={}
    for code,doc in sources.items():
        row=by_code[code]
        old_count=int(row['cross_source_clinical_office_lower_bound'])
        clinical,ambiguous,classified_complete,map_complete=verify_doc(
            code,doc,(float(row['2021_fsa_centroid_latitude']),
                     float(row['2021_fsa_centroid_longitude'])))
        revised=max(old_count,clinical)
        if revised>old_count:
            changed+=1
            new_total+=revised-old_count
        existing=row['merged_google_observation_source_complete']=='True'
        source_fully_compatible=classified_complete and clinical>=old_count
        complete=(existing and clinical<=old_count) or source_fully_compatible
        row['cross_source_clinical_office_lower_bound']=str(revised)
        pop=int(row['population_within_5km_2021_estimate'])
        row['observed_clinical_offices_per_10000_lower_bound']=str(round(10000*revised/pop,9))
        row['residents_per_observed_clinical_office_upper_bound']=str(round(pop/revised,2)) if revised else ''
        row['merged_google_observation_source_complete']='True' if complete else 'False'
        row['new_google_source_status']=doc.get('status','')
        row['new_google_source_18_tiles_complete']=str(map_complete)
        row['new_google_source_ambiguous_offices']=str(ambiguous)
        row['new_google_source_verified_clinical_offices']=str(clinical)
        if complete:completed+=1
        else:unfinished[code]={'source_status':doc.get('status'),'mapped_18_tiles_complete':map_complete,
            'ambiguous_places':ambiguous,'old_clinical':old_count,'new_clinical':clinical}
    for code,row in by_code.items():
        for key in ('new_google_source_status','new_google_source_18_tiles_complete',
                    'new_google_source_ambiguous_offices','new_google_source_verified_clinical_offices'):
            row.setdefault(key,'')
    eligible=[r for r in by_code.values() if r['previously_screened_excluded']=='False']
    # Compare exact integer count/population fractions: floating rounding
    # can falsely make a tied region appear strictly dominated.
    score=lambda r:(Fraction(int(r['cross_source_clinical_office_lower_bound']),
                            int(r['population_within_5km_2021_estimate'])),
                    -int(r['population_within_5km_2021_estimate']),r['fsa'])
    ranked=sorted(eligible,key=score)
    good=[r for r in ranked if r['merged_google_observation_source_complete']=='True']
    cutoff_key=score(good[59]) if len(good)>=60 else None
    cutoff=float(cutoff_key[0])*10000 if cutoff_key is not None else None
    # At equal clinical density, the approved tie-break favours the larger
    # 5-km population and finally the alphabetical three-character FSA.
    # A lower-bound density tied with the cutoff can therefore be excluded
    # ONLY when it cannot outrank the full deterministic cutoff tuple.
    unresolved=[r for r in ranked if r['merged_google_observation_source_complete']!='True'
                and (cutoff_key is None or score(r)<=cutoff_key)]
    ready=cutoff_key is not None and len(unresolved)==0
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    fields=list(next(iter(by_code.values())))
    def write(name,records,rank=False):
        with (out/name).open('w',newline='',encoding='utf8') as fh:
            cols=(['provisional_rank'] if rank else [])+fields
            writer=csv.DictWriter(fh,fieldnames=cols)
            writer.writeheader()
            for i,r in enumerate(records,1):
                writer.writerow({'provisional_rank':i,**r} if rank else r)
    write('Ontario_498_With_New_Google_Source_Rechecks.csv',sorted(by_code.values(),key=lambda r:r['fsa']))
    write('Ontario_498_Rank_Uncertainty_Remaining.csv',unresolved)
    write('Ontario_60_Observed_Clinical_Businesses_Not_Certified.csv',ranked[:60],True)
    if ready:
        write('Ontario_60_Certified_Within_Observed_Google_Model.csv',good[:60],True)
    report={
      'fsa_total':498,'recovered_fsa_checkpoints':len(sources),
      'rechecked_sources_fully_clinical':completed,
      'new_clinical_count_increased_in_fsa':changed,
      'additional_geolocated_clinical_business_lower_bound':new_total,
      'all_eligible_fsa':len(eligible),
      'clinically_complete_eligible_sources':len(good),
      'unresolved_contenders':len(unresolved),
      'cutoff_clinical_offices_per_10000':cutoff,
      'observed_google_source_model_60_verified':ready,
      'all_real_therapists_enumerated':False,
      'incomplete_recheck_details':unfinished,
      'checked_utc':datetime.now(timezone.utc).isoformat()
    }
    (out/'Ontario_Google_Source_Recheck_Report.json').write_text(json.dumps(report,indent=2))
    print('GOOGLE_NEW_SOURCE_RECHECK_RESULT',json.dumps({k:v for k,v in report.items()
        if k!='incomplete_recheck_details'}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--audit',required=True,type=Path)
    p.add_argument('--checkpoints',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    merge(a.audit,a.checkpoints,a.out)
