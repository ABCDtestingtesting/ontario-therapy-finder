"""Strict Ontario 521-FSA source evidence identity and category proof tests."""
import unittest
from research.merge_ontario_521_all_clinic_observations import business_identity,checked_class
from research.external_google_clinical_adjudications import ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS

class BusinessProvinceSourceTests(unittest.TestCase):
    @staticmethod
    def place(name='Northern Psychotherapy',lat=43.2,lon=-79.8,
              googleid='0x882b111111111111:0x1111111111111111'):
        return dict(name=name,lat=lat,lon=lon,
            source_url='https://www.google.com/maps/place/Source/data=!1s'+googleid,
            observed_title_classification='ambiguous')

    def test_same_google_place_id_deduplicates_across_search_names_and_fsas(self):
        p=self.place()
        q=self.place(name='Another business name',lat=43.20001,lon=-79.80001)
        self.assertEqual(business_identity(p),business_identity(q))

    def test_business_without_google_id_falls_back_to_exact_name_and_coordinates(self):
        p=self.place()
        p['source_url']='https://www.google.com/maps/place/Source'
        self.assertEqual(business_identity(p),'northern psychotherapy:43.2:-79.8')

    def test_out_of_ontario_or_unverified_business_url_fails_closed(self):
        for kwargs in (dict(lat=40.2),dict(lon=-100.0)):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(RuntimeError,'coordinates'):
                    business_identity(self.place(**kwargs))
        p=self.place()
        p['source_url']='https://untrusted.example/maps/place/Source'
        with self.assertRaisesRegex(RuntimeError,'provenance'):
            business_identity(p)

    def test_original_clinical_proof_is_preserved(self):
        key,name,lat,lon,gid,url,kind=ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS[0]
        p={'key':key,'name':name,'lat':lat,'lon':lon,
           'source_url':'https://www.google.com/maps/place/Woolwich/data=!1s'+gid,
           'observed_title_classification':'ambiguous'}
        self.assertEqual(kind,'clinical')
        self.assertEqual(checked_class(p),'clinical')

    def test_therapy_named_business_with_independent_massage_proof_is_nonclinical(self):
        key,name,lat,lon,gid,url,kind=ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS[-1]
        p={'key':key,'name':name,'lat':lat,'lon':lon,
           'source_url':'https://www.google.com/maps/place/Business/data=!1s'+gid,
           'observed_title_classification':'clinical'}
        self.assertEqual(kind,'nonclinical')
        self.assertEqual(checked_class(p),'nonclinical')

    def test_clinical_business_source_conflict_must_remain_ambiguous(self):
        p=self.place(name='Niagara Psychotherapy')
        p['observed_title_classification']='nonclinical'
        self.assertEqual(checked_class(p),'ambiguous')

    def test_new_therapist_title_upgrades_original_ambiguous_classification(self):
        self.assertEqual(checked_class(self.place()),'clinical')

if __name__=='__main__':
    unittest.main()
