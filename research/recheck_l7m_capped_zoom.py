"""Recheck one previously capped L7M source tile at 16z.

This check never silently erases original 14z source observations. An uncapped
result must contain a verified Google map position and an explicit end marker.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from research.recover_google_tiles import scan_tile, task_key

CAPPED_TILES = (
    (-3.4,0.0,0,'psychotherapist'),
    (-3.4,3.4,0,'psychotherapist'),
    (0.0,0.0,0,'psychotherapist'),
    (0.0,3.4,0,'psychotherapist'),
    (0.0,3.4,0,'psychologist'),
    (3.4,3.4,0,'psychologist'),
    (-3.4,0.0,0,'psychologist'),
    (3.4,0.0,0,'psychotherapist'),
)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--index',type=int,choices=range(len(CAPPED_TILES)),required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    doc=json.loads(args.source.read_text())
    assert doc.get('fsa')=='L7M'
    task=CAPPED_TILES[args.index]
    key=task_key(task)
    old=doc.get('complete_tiles',{}).get(key)
    if not old or old.get('capped') is not True:
        raise RuntimeError('Missing expected historic L7M capped tile '+key)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        ctx=pw.firefox.launch_persistent_context(str(args.out.parent/'browser_profile'),
            headless=True,viewport={'width':1400,'height':960},locale='en-CA')
        try:
            n,e,_,term=task
            # level=1 only changes search zoom to 16; requested geographic
            # centre is EXACTLY the original tile, not a child/offset.
            new=scan_tile(ctx,'L7M',tuple(doc['center']),n,e,1,term,args.out.parent)
        finally:ctx.close()
    result={'fsa':'L7M','query_key':key,'source_tile_index':args.index,
        'original_capped_tile':old,'verified_zoom16_tile':new}
    args.out.write_text(json.dumps(result,indent=2))
    print('L7M_ZOOM16_TILE_RECHECK',json.dumps({
        'index':args.index,'key':key,'geographic_refresh_verified':new['map_area_search_verified'],
        'capped':new['capped'],'visible_links':new['visible_links'],
        'local_places':len(new['places']),'unresolved':len(new['unresolved']),
        'reason':new['reason']}),flush=True)
    # Capped, blocked, unresolved observations are preserved but remain
    # incomplete; never certify solely because a browser job exited 0.
if __name__=='__main__':main()
