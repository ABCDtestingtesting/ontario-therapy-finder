"""Verify Google place coordinates, and repeat exactly one censored FSA tile.

A place counts only when its canonical Google URL supplies exact coordinates
inside the target 5 km circle. Repeat the K7G censored base category search
at 16z; retain original capped evidence separately in either outcome.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from finder.google_browser import resolve_place_coordinates
from research.recover_google_tiles import scan_tile, task_key, tile_tasks, RADIUS_KM
from research.scan_all_maps import distance_km

CENTER_L7M = (43.417162, -79.870144)
CENTER_K7G = (44.275618, -76.25564)
BUSINESSES={
    'Orange Spark Counselling':'ChIJd4S2HrphK4gRwJj3mgH3wCU',
    'Christina Janiga Psychotherapy':'ChIJEatDC7hhK4gRboEvvZvUsOw',
    'Parenting Solutions for Today\'s Child':None,
    'Brookhaven Psychotherapy':'ChIJ0f7k-AuUmm8RNTFzmundRdE',
}

def l7m(ctx,out):
    rows=[]
    for name, place_id in BUSINESSES.items():
        if place_id is None:
            continue
        href='https://www.google.com/maps/place/?q=place_id%3A'+place_id
        try:
            coords, source=resolve_place_coordinates(ctx,href,timeout_ms=22000)
            distance=round(distance_km(CENTER_L7M,coords),4) if coords else None
            rows.append({'name':name,'place_id':place_id,'coordinates':coords,
                         'google_coordinate_evidence_url':source,
                         'distance_km_from_l7m_center':distance,
                         'eligible_inside_5km':distance is not None and distance<=RADIUS_KM})
        except Exception as exc:
            rows.append({'name':name,'place_id':place_id,
                         'error':str(exc)[:300],'eligible_inside_5km':False})
    out.write_text(json.dumps(rows,indent=2))
    print('L7M_GOOGLE_CANONICAL_PLACE_LOCATIONS',json.dumps(rows),flush=True)

def k7g(ctx,out):
    # The saved baseline contains exactly one geographically verified but capped
    # 14z query (south/east corner). A narrower 16z requery is evidence, not
    # proof that the larger viewport was exhaustively searched.
    code='K7G';center=CENTER_K7G
    north,east,level,term=-3.4,3.4,1,'psychotherapist'
    result=scan_tile(ctx,code,center,north,east,level,term,out.parent)
    out.write_text(json.dumps({
        'fsa':code,'query':term,'north_km':north,'east_km':east,
        'zoom':16,'tile':result,'capped_original_14z_not_superseded':True
    },indent=2))
    print('K7G_HIGHER_ZOOM_GOOGLE_SOURCE',json.dumps({
        'status':result['status'],'capped':result['capped'],
        'visible_links':result['visible_links'],'local_places':len(result['places']),
        'geographic_scoping_verified':result['map_area_search_verified']
    }),flush=True)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--fsa',choices=['K7G','L7M'],required=True)
    a.add_argument('--out',type=Path,required=True)
    args=a.parse_args();args.out.parent.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        ctx=playwright.firefox.launch_persistent_context(
            str(args.out.parent/'browser_profile'),headless=True,
            viewport={'width':1400,'height':960},locale='en-CA')
        try:
            if args.fsa=='L7M':l7m(ctx,args.out)
            else:k7g(ctx,args.out)
        finally:ctx.close()
