"""Google place-detail categories are source evidence, not inferred labels."""
import unittest
from research.finalize_full_google_498 import clinical_title_classification

class GoogleCategoryEvidenceTests(unittest.TestCase):
    def test_verified_google_category_can_resolve_ambiguous_title(self):
        self.assertEqual(clinical_title_classification({
            'name': 'Just For Today', 'google_business_category': 'Counselor'}), 'ambiguous')
        self.assertEqual(clinical_title_classification({
            'name': 'Holistic Mind and Body Wellness',
            'google_business_category': 'Psychotherapist'}), 'clinical')
        self.assertEqual(clinical_title_classification({
            'name': 'Rooted Therapy',
            'google_business_category': 'Marriage or relationship counselor'}), 'clinical')
        self.assertEqual(clinical_title_classification({
            'name': 'The Forest - A Nature-Based Wellness Center',
            'google_business_category': 'Wellness center'}), 'nonclinical')
    def test_title_excludes_nonclinical_even_if_category_conflicts(self):
        self.assertEqual(clinical_title_classification({
            'name': 'Example Physiotherapy', 'google_business_category': 'Counselor'}), 'nonclinical')
    def test_unverified_categories_stay_ambiguous(self):
        self.assertEqual(clinical_title_classification({'name': 'Unclear Wellness'}), 'ambiguous')
        self.assertEqual(clinical_title_classification({
            'name': 'Unclear Wellness', 'google_business_category': 'Medical clinic'}), 'ambiguous')
    def test_occupational_therapy_not_mental_health_evidence(self):
        self.assertEqual(clinical_title_classification({
            'name': 'Everbloom Outdoor Therapy',
            'google_business_category': 'Occupational therapist'}), 'nonclinical')
    def test_only_exact_geographically_verified_settlements_are_nonclinical(self):
        for label, lat, lon in (('Lisle', 44.2680104, -79.9774488),
                                ('Craighurst', 44.529657, -79.725772)):
            self.assertEqual(clinical_title_classification({
                'name': label, 'lat': lat, 'lon': lon,
                'source_url': 'https://www.google.com/maps/place/' + label
            }), 'nonclinical')
            self.assertEqual(clinical_title_classification({
                'name': label, 'lat': 41.5, 'lon': -80.0,
                'source_url': 'https://www.google.com/maps/place/' + label
            }), 'ambiguous')
            self.assertEqual(clinical_title_classification({
                'name': label + ' Psychotherapy', 'lat': lat, 'lon': lon,
                'source_url': 'https://www.google.com/maps/place/' + label
            }), 'clinical')

    def test_positive_title_still_counts_without_category(self):
        self.assertEqual(clinical_title_classification({
            'name': 'Ontario Registered Psychotherapist'}), 'clinical')
if __name__=='__main__':
    unittest.main()
