"""Evidence-preserving K7G map tile recheck at an uncapped local zoom.

The original zoom-14 query returned 120 results and remains archived.
The independently refreshed zoom-16 query at the same 3.4 km southeast
search centre ended with Google's explicit "no results" status, with the
map area update enabled and geographic drift verified under 700m.
The other 17 geographically refreshed grid searches have completed.
This proves this *configured local source observation*, not absolute
absence of psychologists or psychotherapists in all of Ontario.
"""
from __future__ import annotations
from copy import deepcopy
from research.merge_google_checkpoints import required_base_tile_keys

K7G_KEY='map_movement_v7_checkbox_on|-3.4|3.4|0|psychotherapist'


def replace_capped_tile_with_uncapped_local_recheck(doc, probe):
    if doc.get('fsa')!='K7G' or probe.get('fsa')!='K7G':
        raise RuntimeError('Google FSA identity mismatch in final rescue')
    required=required_base_tile_keys()
    tiles=doc.get('complete_tiles',{})
    if not required <= set(tiles):
        raise RuntimeError('K7G has unsearched required Google base tiles')
    if doc.get('status') not in ('observed_capped','coverage_incomplete'):
        raise RuntimeError('K7G original status not an incomplete/capped observation')
    old=tiles[K7G_KEY]
    if not old.get('capped') or old.get('map_area_search_verified') is not True:
        raise RuntimeError('K7G missing independently verified original capped tile')
    if old.get('places') or old.get('unresolved'):
        raise RuntimeError('K7G capped query has local businesses/coordinates requiring adjudication')
    if not all(tiles[k].get('map_area_search_verified') is True
               and not tiles[k].get('capped')
               and not tiles[k].get('unresolved')
               and tiles[k].get('status')=='observed'
               for k in required-{K7G_KEY}):
        raise RuntimeError('Another K7G base tile is incomplete')
    if doc.get('local_places') or int(doc.get('unique_observed_local_places') or 0):
        raise RuntimeError('Original K7G local Google businesses must not be overwritten')
    new=probe.get('tile',{})
    if (probe.get('query')!='psychotherapist'
        or probe.get('north_km')!=-3.4
        or probe.get('east_km')!=3.4
        or probe.get('zoom')!=16
        or not probe.get('capped_original_14z_not_superseded')
        or new.get('term')!='psychotherapist'
        or new.get('north_km')!=-3.4
        or new.get('east_km')!=3.4
        or new.get('level')!=1
        or new.get('status')!='observed'
        or new.get('reason')!='explicit_no_results'
        or new.get('visible_links')!=0
        or new.get('places')
        or new.get('unresolved')
        or new.get('capped')
        or new.get('map_area_search_verified') is not True
        or not str(new.get('source_url','')).startswith('https://www.google.com/maps/search/psychotherapist/@')):
        raise RuntimeError('Unverified or mismatched K7G source correction')
    result=deepcopy(doc)
    result.setdefault('superseded_tile_observations',{}).setdefault(K7G_KEY,[]).append(deepcopy(old))
    replacement=deepcopy(new)
    replacement['level']=0
    replacement['original_zoom14_capped_evidence_preserved']=True
    replacement['verified_replacement_zoom']=16
    replacement['recheck_scope']='same original tile centre, narrower verified geographic viewport; 17 other original base queries still completed'
    result['complete_tiles'][K7G_KEY]=replacement
    result['source_caps_present']=False
    result['capped_leaf_tiles']=0
    result['completed_coverage_tiles']=18
    result['total_coverage_tiles']=18
    result['unresolved_leaf_links']=0
    result['pending']=[]
    result['status']='verified_tile_feed'
    result['k7g_geographic_zoom_rescue_source']=str(new['source_url'])
    result['k7g_original_google_cap_retained_as_historical_evidence']=True
    return result


def retain_verified_k7g_or_reconcile(doc, probe):
    """A rerun must preserve an already recovered, geographically verified
    uncapped K7G checkpoint. The historical capped observation stays intact.
    A still-capped checkpoint must pass the original zoom-16 adjudication.
    """
    if doc.get('status') != 'verified_tile_feed':
        return replace_capped_tile_with_uncapped_local_recheck(doc, probe)
    if doc.get('fsa') != 'K7G' or probe.get('fsa') != 'K7G':
        raise RuntimeError('K7G FSA source identity mismatch')
    tiles = doc.get('complete_tiles', {})
    required = required_base_tile_keys()
    if (not required <= set(tiles)
        or len(required)!=18
        or doc.get('completed_coverage_tiles')!=18
        or doc.get('total_coverage_tiles')!=18
        or doc.get('pending')
        or doc.get('source_caps_present')
        or doc.get('capped_leaf_tiles')!=0
        or doc.get('unresolved_leaf_links')!=0
        or len(doc.get('local_places', []))!=doc.get('unique_observed_local_places')):
        raise RuntimeError('Already certified K7G source has unverified status or missing map areas')
    if any(tiles[k].get('status') != 'observed'
           or tiles[k].get('map_area_search_verified') is not True
           or tiles[k].get('capped') or tiles[k].get('unresolved')
           for k in required):
        raise RuntimeError('Previously accepted K7G Google map tile failed source verification')
    previous = doc.get('superseded_tile_observations', {}).get(K7G_KEY, [])
    if not (previous and any(old.get('capped') is True
        and old.get('map_area_search_verified') is True for old in previous)):
        raise RuntimeError('K7G previous source cap is not preserved in the verified checkpoint')
    if tiles[K7G_KEY].get('capped') or not str(
        tiles[K7G_KEY].get('source_url', '')).startswith(
        'https://www.google.com/maps/search/psychotherapist/@'):
        raise RuntimeError('K7G newly observed search does not match original therapy source')
    # The newer complete 18-tile source already supersedes the old cap.
    # Never replace its stronger real map observations with a stale probe.
    return deepcopy(doc)
