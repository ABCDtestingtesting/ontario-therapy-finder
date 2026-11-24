"""Exact identity and source integrity for externally corroborated clinical places."""
import unittest
from research.external_google_clinical_adjudications import (
    EVIDENCE, independent_clinical_service_evidence)
from research.finalize_full_google_498 import clinical_title_classification

def example(row):
    key,name,lat,lon,url = row
    return {'key':key, 'name':name, 'lat':lat,'lon':lon,
      'source_url':'https://www.google.com/maps/place/'+name.replace(' ','+')+'/data=!4m7!3m6!1s'+key.removeprefix('google:')}

class ExternallyGroundedTherapistTests(unittest.TestCase):
    def test_all_manual_claims_have_exact_google_coordinates_and_cited_clinical_sources(self):
        self.assertEqual(len(EVIDENCE),8)
        self.assertEqual(len({r[0] for r in EVIDENCE}),8)
        for row in EVIDENCE:
            with self.subTest(name=row[1]):
                src=example(row)
                self.assertEqual(independent_clinical_service_evidence(src),row[-1])
                self.assertEqual(clinical_title_classification(src),'clinical')

    def test_no_google_place_id_is_accepted_from_name_alone(self):
        row=example(EVIDENCE[0])
        row.pop('key')
        self.assertIsNone(independent_clinical_service_evidence(row))
        self.assertEqual(clinical_title_classification(row),'ambiguous')

    def test_no_clinical_claim_without_matching_name_and_place_url(self):
        for field,override in [('name','Credit Counselling'),
                               ('source_url','https://other.example/maps/place/'), 
                               ('key','google:0x111:0x222')]:
            with self.subTest(field=field):
                src=example(EVIDENCE[0]);src[field]=override
                self.assertIsNone(independent_clinical_service_evidence(src))

    def test_geographic_mismatch_fails_closed(self):
        for coordinate in ('lat','lon'):
            src=example(EVIDENCE[0])
            src[coordinate]=src[coordinate]+0.1
            self.assertIsNone(independent_clinical_service_evidence(src))

    def test_title_evidence_does_not_prove_registered_individuals(self):
        src=example(EVIDENCE[0])
        self.assertEqual(clinical_title_classification(src),'clinical')
        self.assertNotIn('registered_therapist_count',src)
        self.assertNotIn('patient_capacity',src)

if __name__=='__main__':
    unittest.main()
