"""Exact identity and source integrity for externally corroborated clinical places."""
import unittest
from research.external_google_clinical_adjudications import (
    EVIDENCE, ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS,
    independent_clinical_service_evidence,
    independent_nonclinical_service_evidence,
    original_google_business_corroboration)
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

    def original_place(self, row):
        key,name,lat,lon,google_id,evidence_url,kind=row
        return {'key':key,'name':name,'lat':lat,'lon':lon,
            'source_url':'https://www.google.com/maps/place/'+name.replace(' ','+')+
                '/data=!4m7!3m6!1s'+google_id}

    def test_all_original_google_correspondences_have_evidence_and_proper_modality(self):
        self.assertEqual(len(ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS),10)
        self.assertEqual(sum(r[-1]=='clinical' for r in ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS),9)
        for record in ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS:
            with self.subTest(name=record[1]):
                place=self.original_place(record)
                observed=original_google_business_corroboration(place)
                self.assertEqual(observed,(record[-1],record[-2]))
                self.assertEqual(clinical_title_classification(place),record[-1])
                if record[-1]=='clinical':
                    self.assertEqual(independent_clinical_service_evidence(place),record[-2])
                else:
                    self.assertEqual(independent_nonclinical_service_evidence(place),record[-2])
                    self.assertIsNone(independent_clinical_service_evidence(place))

    def test_original_google_id_name_and_coordinate_mismatches_fail_closed(self):
        row=ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS[0]
        original=self.original_place(row)
        for change in ({'key':'other'}, {'name':'Another Counseling Center'},
                       {'source_url':'https://www.google.com/maps/place/Noid'},
                       {'lat':original['lat']+0.01},
                       {'lon':original['lon']+0.01}):
            with self.subTest(change=change):
                place=dict(original,**change)
                self.assertIsNone(original_google_business_corroboration(place))
                self.assertIsNone(independent_clinical_service_evidence(place))

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
