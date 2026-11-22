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
