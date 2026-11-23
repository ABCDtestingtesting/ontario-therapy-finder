"""Merge historical and current Google observations without losing locations."""
from copy import deepcopy

from research.recover_google_tiles import tile_tasks, task_key


def combine_google_checkpoints(old, new):
    """Return (checkpoint, reason); never promote incomplete source evidence."""
    code = old.get('fsa')
    if not code or new.get('fsa') != code:
        raise RuntimeError('Mismatched Google FSA source identity')
    old_tiles = old.get('complete_tiles', {})
    new_tiles = new.get('complete_tiles', {})
    old_places = old.get('local_places', [])
    new_places = new.get('local_places', [])
    if not isinstance(old_tiles, dict) or not isinstance(new_tiles, dict):
        raise RuntimeError('Malformed Google tile checkpoint')
    if not isinstance(old_places, list) or not isinstance(new_places, list):
        raise RuntimeError('Malformed Google local place checkpoint')
    if (len(old_places) != int(old.get('unique_observed_local_places') or 0) or
            len(new_places) != int(new.get('unique_observed_local_places') or 0)):
        raise RuntimeError('Google checkpoint local place count inconsistent')
    required = {task_key(task) for task in tile_tasks()}
    current_complete = (
        new.get('status') == 'verified_tile_feed'
        and required <= set(new_tiles)
        and not new.get('pending')
        and not new.get('capped_leaf_tiles')
        and not new.get('unresolved_leaf_links')
        and all(new_tiles[k].get('status') == 'observed'
                and not new_tiles[k].get('capped')
                and not new_tiles[k].get('unresolved')
                and new_tiles[k].get('map_area_search_verified') is True
                for k in required)
    )
    if (old.get('status') == 'verified_tile_feed'
            and new.get('status') != 'verified_tile_feed'):
        return old, 'preserved_complete_original'
    if (not current_complete and
            (not set(old_tiles) <= set(new_tiles)
             or len(new_places) < len(old_places))):
        return old, 'new_checkpoint_lost_source_evidence'
    # Keep every historical actual place and every old tile source, including
    # evidence from legacy searches; new fully verified base tiles supersede
    # their older versions only when those queries were reobserved.
    out = deepcopy(new)
    old_local = {p['key']: deepcopy(p) for p in old_places}
    combined = old_local
    for place in new_places:
        key = place['key']
        earlier = combined.get(key, {})
        merged = deepcopy(place)
        for field in ('google_business_category', 'google_category_checked_at',
                      'google_category_evidence_url'):
            if not merged.get(field) and earlier.get(field):
                merged[field] = earlier[field]
        combined[key] = merged
    out['local_places'] = list(combined.values())
    out['unique_observed_local_places'] = len(combined)
    merged_tiles = deepcopy(old_tiles)
    for key, tile in new_tiles.items():
        if key in merged_tiles and merged_tiles[key] != tile:
            previous = merged_tiles[key]
            out.setdefault('superseded_tile_observations', {}).setdefault(key, []).append(previous)
            newer = deepcopy(tile)
            older = {p['key']: p for p in previous.get('places', [])}
            older.update({p['key']: p for p in newer.get('places', [])})
            newer['places'] = list(older.values())
            merged_tiles[key] = newer
        else:
            merged_tiles[key] = deepcopy(tile)
    out['complete_tiles'] = merged_tiles
    out['preserved_old_source_tile_count'] = len(old_tiles)
    out['preserved_old_local_place_count'] = len(old_places)
    if current_complete:
        out['status'] = 'verified_tile_feed'
        out['pending'] = []
        out['capped_leaf_tiles'] = 0
        out['unresolved_leaf_links'] = 0
        out['completed_coverage_tiles'] = len(required)
        out['total_coverage_tiles'] = len(required)
        return out, 'verified_new_core_with_all_older_evidence'
    return out, 'merged_monotonic_noncertified_evidence'
