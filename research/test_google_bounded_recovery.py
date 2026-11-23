"""Regression tests for bounded Ontario Google Maps recovery checkpoints."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.recover_google_tiles import run_area, tile_tasks, task_key, SEARCHES


class BoundedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.area = {'fsa': 'M3J', 'lat': 43.76, 'lon': -79.48, 'population_2021': 10000}

    @staticmethod
    def evidence(context, code, center, north, east, level, term, root):
        return {
            'level': level, 'capped': True, 'unresolved': [],
            'places': [{'key': 'google:unique', 'name': 'Test clinic',
                        'lat': 43.76, 'lon': -79.48, 'source_url': 'https://google.com/maps/place/a'}],
            'term': term,
        }

    def test_localized_queries_have_distinct_keys_from_legacy_generic_cells(self):
        self.assertEqual(SEARCHES, ('psychotherapist', 'psychologist'))
        self.assertEqual(len(list(tile_tasks())), 18)
        self.assertTrue(all('{FSA}' not in task[3] for task in tile_tasks()))
        self.assertNotIn('-3.4|-3.4|0|psychotherapist', {task_key(t) for t in tile_tasks()})

    def test_bounded_search_cap_never_recurses(self):
        with patch('research.recover_google_tiles.scan_tile', side_effect=self.evidence) as scan:
            row = run_area(None, self.area, self.folder, 1000)
        self.assertEqual(scan.call_count, 18)
        self.assertEqual(row['completed_coverage_tiles'], 18)
        self.assertEqual(row['unique_observed_local_places'], 1)
        self.assertEqual(row['status'], 'observed_capped')
        self.assertEqual(len(row['pending']), 0)
        self.assertEqual(row['capped_leaf_tiles'], 18)

    def test_legacy_queue_is_discarded_without_deleting_evidence(self):
        old = self.evidence(None, 'M3J', None, 0, 0, 2, 'psychotherapist', None)
        previous = {'fsa': 'M3J', 'complete_tiles': {'legacy-tile': old},
                    'pending': [[0.0, 0.0, 2, 'psychotherapist']] * 999,
                    'attempts': 40, 'status': 'coverage_incomplete'}
        (self.folder / 'M3J.json').write_text(json.dumps(previous))
        with patch('research.recover_google_tiles.scan_tile', side_effect=self.evidence) as scan:
            row = run_area(None, self.area, self.folder, 1000)
        self.assertEqual(scan.call_count, 18)
        self.assertIn('legacy-tile', row['complete_tiles'])
        self.assertEqual(row['status'], 'observed_capped')
        self.assertEqual(row['unique_observed_local_places'], 1)
        self.assertEqual(row['recovery_plan'], 'fixed_18_map_movement_v6_categories_geographically_scoped')

    def test_failed_source_is_never_zero_competitors(self):
        with patch('research.recover_google_tiles.scan_tile', side_effect=RuntimeError('source unavailable')) as scan:
            row = run_area(None, self.area, self.folder, 1000)
        self.assertEqual(scan.call_count, 18)
        self.assertEqual(len(row['pending']), 18)
        self.assertEqual(row['status'], 'coverage_incomplete')
        self.assertEqual(len(row['tile_failures']), 18)

    def test_resume_reuses_all_successful_base_tiles(self):
        part = {'fsa': 'M3J', 'complete_tiles': {}, 'attempts': 0,
                'status': 'coverage_incomplete', 'pending': list(tile_tasks())}
        for task in list(tile_tasks())[:12]:
            part['complete_tiles'][task_key(task)] = self.evidence(
                None, 'M3J', None, *task, None)
        (self.folder / 'M3J.json').write_text(json.dumps(part))
        with patch('research.recover_google_tiles.scan_tile', side_effect=self.evidence) as scan:
            row = run_area(None, self.area, self.folder, 1000)
        self.assertEqual(scan.call_count, 6)
        self.assertEqual(row['completed_coverage_tiles'], 18)

    def test_rank_dominated_without_any_new_search(self):
        enriched = dict(self.area, ranking_cutoff=3000.0,
                        population_5km_estimate=40000,
                        baseline_observed_5km=14)
        with patch('research.recover_google_tiles.scan_tile', side_effect=self.evidence) as scan:
            row = run_area(None, enriched, self.folder, 1000)
        self.assertEqual(scan.call_count, 0)
        self.assertEqual(row['status'], 'rank_dominated_early')
        self.assertEqual(len(row['pending']), 18)

    def test_rank_dominated_after_evidence_added(self):
        enriched = dict(self.area, ranking_cutoff=3000.0,
                        population_5km_estimate=40000,
                        baseline_observed_5km=12)
        def unique_evidence(context, code, center, north, east, level, term, root):
            e = self.evidence(context, code, center, north, east, level, term, root)
            e['places'] = [{'key': 'extra' + str(i)} for i in range(2)]
            return e
        with patch('research.recover_google_tiles.scan_tile', side_effect=unique_evidence) as scan:
            row = run_area(None, enriched, self.folder, 1000)
        self.assertEqual(scan.call_count, 18)
        self.assertFalse(row['rank_dominated_by_verified_cutoff'])

    def test_uncapped_complete_has_distinct_verified_status(self):
        def no_cap(*args):
            e = self.evidence(*args)
            e['capped'] = False
            return e
        with patch('research.recover_google_tiles.scan_tile', side_effect=no_cap):
            row = run_area(None, self.area, self.folder, 1000)
        self.assertEqual(row['status'], 'verified_tile_feed')


if __name__ == '__main__':
    unittest.main()
