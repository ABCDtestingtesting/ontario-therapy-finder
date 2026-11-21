"""Audit the ACTUAL per-area browser work the user would be asked to perform.

This deliberately makes no requests to Google or Psychology Today.
Small CI probes do not demonstrate completion of the full program.
"""
from __future__ import annotations
import json, math
from finder import census,maps,google_browser

CODES=('L7A','L6Z','N1T')
def main():
    boundaries=census.fsa_geometry(print)
    report={'test_kind':'FULL_5KM_SEARCH_PLAN_NOT_A_COMPLETED_SEARCH',
            'queries_per_grid_cell':len(maps.SEARCHES),
            'source_types':['Google Maps Firefox browser','Psychology Today','2021 Census','Street View'],
            'areas':{},'automated_full_area_search_run':False}
    for code in CODES:
        geom=boundaries[code]
        bbox=maps.bbox_with_margin(geom)
        south,west,north,east=[float(x) for x in bbox.split(',')]
        cells=sum(1 for _ in google_browser.grid_points((south,west,north,east)))
        jobs=cells*len(maps.SEARCHES)
        report['areas'][code]={'search_bbox':bbox,'grid_cells':cells,
           'per_cell_terms':len(maps.SEARCHES),'total_google_searches':jobs,
           'lower_bound_minutes_one_second_per_search':round(jobs/60,1),
           'upper_bound_hours_each_search_90_seconds':round(jobs*90/3600,1)}
        print(code,report['areas'][code],flush=True)
    with open('ci/collection_feasibility.json','w') as f:json.dump(report,f,indent=2)
    print('RESULT: planning feasibility only; no successful completed grid is demonstrated.',flush=True)
if __name__=='__main__':main()
