"""Reconcile original capped L7M map cells and eight higher-zoom checks.

Retain all historically observed Google business IDs, sources, categories, and
the original capped map feeds. Never certify a missing/capped/unlocated or
geographically unverified refreshed search.
"""
from copy import deepcopy
from research.merge_google_checkpoints import required_base_tile_keys
from research.recheck_l7m_capped_zoom import CAPPED_TILES
from research.recover_google_tiles import task_key

def merge_l7m_rechecks(doc, rows):
    if doc.get('fsa')!='L7M':
        raise RuntimeError('Wrong L7M FSA source')
    required=required_base_tile_keys()
    tiles=doc.get('complete_tiles',{})
    if not required <= set(tiles) or len(rows)!=len(CAPPED_TILES):
        raise RuntimeError('Missing L7M base Google source or zoom recheck')
    result=deepcopy(doc)
    places={p['key']:deepcopy(p) for p in result.get('local_places',[])}
    newly_seen=0
    remaining=[]
    for index,task in enumerate(CAPPED_TILES):
        row=rows[index]
        key=task_key(task)
        if (row.get('fsa')!='L7M'
                or row.get('query_key')!=key
                or row.get('source_tile_index')!=index
                or not tiles[key].get('capped')):
            raise RuntimeError('L7M zoom source identity mismatch '+str(index))
        new=row.get('verified_zoom16_tile',{})
        north,east,level,term=task
        if (new.get('term')!=term or new.get('north_km')!=north
                or new.get('east_km')!=east or new.get('level')!=1
                or new.get('map_area_search_verified') is not True
                or new.get('status') not in ('observed','observed_partial')
                or not str(new.get('source_url','')).startswith('https://www.google.com/maps/search/')):
            raise RuntimeError('L7M replacement search not geographically verified '+str(index))
        for place in new.get('places',[]):
            earlier=places.get(place['key'],{})
            merged=deepcopy(place)
            for field in ('google_business_category','google_category_checked_at',
                          'google_category_evidence_url'):
                if not merged.get(field) and earlier.get(field):
                    merged[field]=earlier[field]
            if place['key'] not in places:
                newly_seen+=1
            places[place['key']]=merged
        if (new.get('capped') or new.get('unresolved')
                or new.get('reason') not in ('explicit_no_results','visible_end_of_list','single_place_panel')):
            remaining.append(index)
            continue
        old=tiles[key]
        result.setdefault('superseded_tile_observations',{}).setdefault(key,[]).append(deepcopy(old))
        fresh=deepcopy(new)
        fresh['level']=level
        fresh['recheck_zoom']=16
        fresh['original_capped_14z_source_preserved']=True
        old_places={p['key']:deepcopy(p) for p in old.get('places',[])}
        old_places.update({p['key']:deepcopy(p) for p in fresh.get('places',[])})
        fresh['places']=list(old_places.values())
        result['complete_tiles'][key]=fresh
    result['local_places']=list(places.values())
    result['unique_observed_local_places']=len(places)
    result['l7m_zoom_recheck_attempts']=len(rows)
    result['l7m_zoom_recheck_new_unique_local_places']=newly_seen
    result['l7m_zoom_recheck_incomplete_indices']=remaining
    capped=sum(bool(result['complete_tiles'][k].get('capped')) for k in required)
    unresolved=sum(len(result['complete_tiles'][k].get('unresolved',[])) for k in required)
    result['capped_leaf_tiles']=capped
    result['unresolved_leaf_links']=unresolved
    result['completed_coverage_tiles']=len(required)
    result['total_coverage_tiles']=len(required)
    result['pending']=[]
    result['source_caps_present']=bool(capped)
    fully_observed=all(
        result['complete_tiles'][k].get('status')=='observed'
        and result['complete_tiles'][k].get('map_area_search_verified') is True
        and not result['complete_tiles'][k].get('capped')
        and not result['complete_tiles'][k].get('unresolved')
        for k in required)
    result['status']='verified_tile_feed' if fully_observed else (
        'coordinates_unresolved' if unresolved and not capped else 'observed_capped')
    return result
