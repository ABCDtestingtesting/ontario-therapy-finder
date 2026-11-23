"""Compare Google Maps result caps at fixed map centres, zoom 14, 15, 16.

Use exactly the same current Google Maps query and checkbox refresh, and
record source URLs, geographic drift, all result coordinates, source caps,
and visible end markers; never certify the complete 5 km search by zoom alone.
"""
import argparse,json,time
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
from finder import google_browser
from finder.google_browser import scan_one
from research.google_measured_recenter_runner import refresh
from research.scan_all_maps import distance_km,global_place_coordinates

AREA={'P4N':(48.400117,-81.483894),'K7L':(44.305340,-76.352948),
      'L9E':(43.507757,-79.792617)}

def run(fsa,term,zoom,out):
    centre=AREA[fsa]
    out.parent.mkdir(parents=True,exist_ok=True)
    google_browser._refresh_map_area_results=refresh
    with sync_playwright() as pw:
        ctx=pw.firefox.launch_persistent_context(
            str(out.parent/'profile'),headless=True,locale='en-CA',
            viewport={'width':1400,'height':960})
        try:
            raw=scan_one(ctx,term,*centre,out.parent/'evidence',
                         zoom=zoom,timeout_seconds=65,max_scroll=22,
                         force_map_refresh=True)
        finally:ctx.close()
    inside=[]
    outside=[]
    missing=[]
    for place in raw.get('place_links',[]):
        coord=place.get('coordinates') or global_place_coordinates(place.get('url',''))
        if not coord:
            missing.append(place.get('name'));continue
        distance=distance_km(centre,coord)
        (inside if distance<=5 else outside).append({
            'name':place.get('name'),'distance_km':round(distance,3),
            'source_url':place.get('url')})
    report={'fsa':fsa,'term':term,'zoom':zoom,
            'geographic_refresh_verified':raw.get('geographic_refresh_verified'),
            'completion_reason':raw.get('completion_reason'),
            'completed':raw.get('completed'),
            'visible_source_links':len(raw.get('place_links',[])),
            'within_5km_count':len(inside),
            'outside_5km_count':len(outside),
            'unlocatable_count':len(missing),
            'within_5km_businesses':inside,
            'outside_5km_nearest_10':sorted(outside,key=lambda p:p['distance_km'])[:10],
            'recorded_at_utc':datetime.now(timezone.utc).isoformat()}
    out.write_text(json.dumps(report,indent=2))
    print('GOOGLE_ZOOM_SCOPE_PROBE',json.dumps({
        k:v for k,v in report.items()
        if k not in ('within_5km_businesses','outside_5km_nearest_10')}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fsa',choices=AREA,required=True)
    p.add_argument('--term',required=True);p.add_argument('--zoom',type=int,choices=(14,15,16),required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    run(a.fsa,a.term,a.zoom,a.out)
