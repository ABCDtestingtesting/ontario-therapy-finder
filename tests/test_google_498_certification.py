"""Regression checks for Google-only 498 FSA source certification."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.finalize_full_google_498 import (
    clinical_recovery_lower_bound,
    confirmed_clinical_title,
    independent_grid_empty_evidenced,
    independent_grid_searches_complete,
    recovery_clinically_classified,
)


class GoogleSourceCertificationTests(unittest.TestCase):
    def test_physiotherapy_does_not_count_as_psychotherapy(self):
        self.assertFalse(confirmed_clinical_title({'name': 'Physiotherapy and Wellness Clinic'}))
        self.assertFalse(confirmed_clinical_title({'name': 'Pet Counselling and Dog Training'}))
        self.assertTrue(confirmed_clinical_title({'name': 'Registered Psychotherapist Ontario'}))
        self.assertTrue(confirmed_clinical_title({'name': 'Counselling and Mental Health Centre'}))

    def test_unclassified_google_listings_cannot_prove_completed_clinical_count(self):
        source = {
            'status': 'verified_tile_feed',
            'unique_observed_local_places': 3,
            'local_places': [
                {'name': 'Psychotherapy and Counselling'},
                {'name': 'Physiotherapy Associates'},
                {'name': 'Wellness Services'},
            ],
        }
        self.assertEqual(clinical_recovery_lower_bound(source), 1)
        self.assertFalse(recovery_clinically_classified(source))

    def test_explicitly_unrelated_businesses_do_not_invalidate_complete_source(self):
        source = {
            'unique_observed_local_places': 2,
            'local_places': [
                {'name': 'Physiotherapy Associates'},
                {'name': 'Registered Psychotherapist'},
            ],
        }
        self.assertEqual(clinical_recovery_lower_bound(source), 1)
        self.assertTrue(recovery_clinically_classified(source))

    def test_all_confirmed_mental_health_listings_can_pass_classification(self):
        source = {
            'unique_observed_local_places': 2,
            'local_places': [
                {'name': 'Registered Psychotherapist'},
                {'name': 'Psychology Services'},
            ],
        }
        self.assertEqual(clinical_recovery_lower_bound(source), 2)
        self.assertTrue(recovery_clinically_classified(source))

    def test_search_results_not_written_to_csv_fail_even_after_completed_grid(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            evidence = root / 'native_evidence.json'
            (root / 'run_plan.json').write_text(json.dumps({
                'bbox': '43.0,-80.0,43.0001,-79.9999',
                'grid_cell_km': 5, 'terms': ['a', 'b', 'c', 'd'],
            }))
            lines = [{'message': '20 places found'}]
            for i in range(4):
                lines.append({
                    'message': 'job finished',
                    'status': 'success',
                    'job': (
                        'URL: (https://www.google.com/maps/search/'
                        + str(i)
                        + '/@43.00005,-79.99995,16z, UrlParams: {})'),
                })
            lines.append({'message': 'scrapemate exited'})
            (root / 'collector.log').write_text(
                '\\n'.join(json.dumps(line) for line in lines))
            with (root / 'native_google_raw.csv').open('w', newline='') as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=['title', 'latitude', 'longitude', 'link'])
                writer.writeheader()
                writer.writerow({'title': 'Therapist',
                                 'latitude': '43.0', 'longitude': '-80.0',
                                 'link': 'https://www.google.com/maps/'})
            meta = {'process_returncode': 0, 'raw_rows': 1}
            evidence.write_text(json.dumps(meta))
            self.assertFalse(independent_grid_searches_complete(meta, evidence),
                             'Twenty Google source places cannot yield a complete one-row CSV')

    def test_missing_or_empty_file_does_not_prove_zero_therapists(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'native_evidence.json'
            meta = {'source_empty_or_missing': True,
                    'raw_rows': None,
                    'process_returncode': 0,
                    'status': 'source_failed'}
            p.write_text(json.dumps(meta))
            self.assertFalse(independent_grid_empty_evidenced(meta, p))
            # Even when a workflow mistakenly labels zero as verified,
            # missing CSV evidence is still insufficient.
            meta.update(source_empty_or_missing=False,
                        raw_rows=0, status='grid_empty_verified')
            self.assertFalse(independent_grid_empty_evidenced(meta, p))

    def test_nonzero_raw_count_without_mental_health_title_stays_ambiguous(self):
        source = {
            'unique_observed_local_places': 1,
            'local_places': [{'name': 'General Health and Rehabilitation'}],
        }
        self.assertEqual(clinical_recovery_lower_bound(source), 0)
        self.assertFalse(recovery_clinically_classified(source))


if __name__ == '__main__':
    unittest.main()
