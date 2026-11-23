"""Regressions for monotonic geographic Google source merging."""
import unittest

from research.merge_google_checkpoints import combine_google_checkpoints
from research.recover_google_tiles import tile_tasks, task_key


def place(key):
    return {'key': key, 'name': key, 'source_url': 'https://google.com/maps/place/'+key}


def verified():
    tiles = {
        task_key(t): {
            'places': [], 'status': 'observed',
            'capped': False, 'unresolved': [], 'map_area_search_verified': True,
        } for t in tile_tasks()
    }
    return {
        'fsa': 'L4M', 'status': 'verified_tile_feed',
        'complete_tiles': tiles, 'local_places': [place('new')],
        'unique_observed_local_places': 1, 'pending': [],
        'capped_leaf_tiles': 0, 'unresolved_leaf_links': 0,
    }


class CheckpointMergeTests(unittest.TestCase):
    def test_old_google_place_and_legacy_tile_survive_fresh_18_query_completion(self):
        previous = {
            'fsa': 'L4M', 'status': 'coverage_incomplete',
            'complete_tiles': {'legacy_query': {'places': [place('old')]}},
            'local_places': [place('old'), place('clinic')],
            'unique_observed_local_places': 2,
        }
        newer = verified()
        result, why = combine_google_checkpoints(previous, newer)
        self.assertEqual(why, 'verified_new_core_with_all_older_evidence')
        self.assertEqual(result['status'], 'verified_tile_feed')
        self.assertEqual(set(p['key'] for p in result['local_places']),
                         {'old', 'clinic', 'new'})
        self.assertIn('legacy_query', result['complete_tiles'])
        self.assertEqual(len(result['complete_tiles']), 19)

    def test_incomplete_superseder_cannot_erase_old_places(self):
        old = verified()
        new = verified()
        new['status'] = 'coverage_incomplete'
        new['local_places'] = []
        new['unique_observed_local_places'] = 0
        result, why = combine_google_checkpoints(old, new)
        self.assertEqual(why, 'preserved_complete_original')
        self.assertEqual(result['status'], 'verified_tile_feed')
        self.assertEqual(result['unique_observed_local_places'], 1)

    def test_new_verified_flag_without_valid_geographic_source_is_rejected(self):
        old = {
            'fsa': 'L4M', 'status': 'coverage_incomplete',
            'complete_tiles': {'legacy_query': {'places': []}},
            'local_places': [], 'unique_observed_local_places': 0
        }
        new = verified()
        first = task_key(next(iter(tile_tasks())))
        new['complete_tiles'][first]['map_area_search_verified'] = False
        result, why = combine_google_checkpoints(old, new)
        self.assertEqual(why, 'new_checkpoint_lost_source_evidence')
        self.assertEqual(result, old)

    def test_category_evidence_survives_refresh(self):
        previous = verified()
        previous['status'] = 'coverage_incomplete'
        previous['local_places'][0]['google_business_category'] = 'Psychotherapist'
        newer = verified()
        result, _ = combine_google_checkpoints(previous, newer)
        self.assertEqual(result['local_places'][0]['google_business_category'], 'Psychotherapist')


if __name__ == '__main__':
    unittest.main()
