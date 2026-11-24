"""Regression suite: recovered Google source cannot imply missing therapists."""
import csv,json,tempfile,unittest
from pathlib import Path
from research.reconcile_priority_google_rechecks import merge,TILE_KEYS

class PriorityGoogleRecoveryReconciliationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.source=self.root/'all-498.csv'
        self.maps=self.root/'recovered'
        self.maps.mkdir()
        self.out=self.root/'result'
        self.codes=[f'{a}{d}{c}' for a in 'KLMNP' for d in '0123456789'
                    for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'][:498]
        fields=['fsa','previously_screened_excluded','merged_google_observation_source_complete',
                'cross_source_clinical_office_lower_bound',
                'population_within_5km_2021_estimate',
                'observed_clinical_offices_per_10000_lower_bound',
                'residents_per_observed_clinical_office_upper_bound',
                '2021_fsa_centroid_latitude','2021_fsa_centroid_longitude']
        with self.source.open('w',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=fields)
            writer.writeheader()
            for code in self.codes:
                writer.writerow({'fsa':code,'previously_screened_excluded':'False',
                    'merged_google_observation_source_complete':'False',
                    'cross_source_clinical_office_lower_bound':0,
                    'population_within_5km_2021_estimate':10000,
                    'observed_clinical_offices_per_10000_lower_bound':0,
                    'residents_per_observed_clinical_office_upper_bound':'',
                    '2021_fsa_centroid_latitude':43.7,
                    '2021_fsa_centroid_longitude':-79.5})

    def document(self,clinical=True,capped=False,remote=False,unknown=False):
        key=self.codes[0]
        place={'key':'unique-google-1',
               'name':'Unidentified Wellness' if unknown else 'Example Psychotherapy',
               'source_url':'https://www.google.com/maps/place/Example',
               'lat':47.0 if remote else 43.7,'lon':-79.5}
        return {'fsa':key,'center':[43.7,-79.5],
          'status':'observed_capped' if capped else 'verified_tile_feed',
          'complete_tiles':{k:{'status':'observed',
                'map_area_search_verified':True,'capped':capped,
                'unresolved':[]} for k in TILE_KEYS},
          'completed_coverage_tiles':18,'total_coverage_tiles':18,
          'pending':[],'capped_leaf_tiles':1 if capped else 0,
          'unresolved_leaf_links':0,'source_caps_present':capped,
          'unique_observed_local_places':1,'local_places':[place]}

    def save(self,doc):
        (self.maps/(self.codes[0]+'.json')).write_text(json.dumps(doc))

    def test_clinically_verified_grid_only_marks_one_area_complete(self):
        self.save(self.document())
        result=merge(self.source,self.maps,self.out)
        self.assertEqual(result['recovered_fsa_checkpoints'],1)
        self.assertEqual(result['rechecked_sources_fully_clinical'],1)
        self.assertEqual(result['additional_geolocated_clinical_business_lower_bound'],1)
        self.assertEqual(result['clinically_complete_eligible_sources'],1)
        self.assertFalse(result['observed_google_source_model_60_verified'])
        self.assertFalse((self.out/'Ontario_60_Certified_Within_Observed_Google_Model.csv').exists())

    def test_a_capped_search_keeps_location_but_no_false_completion(self):
        self.save(self.document(capped=True))
        result=merge(self.source,self.maps,self.out)
        self.assertEqual(result['additional_geolocated_clinical_business_lower_bound'],1)
        self.assertEqual(result['rechecked_sources_fully_clinical'],0)
        self.assertEqual(result['clinically_complete_eligible_sources'],0)

    def test_ambiguous_business_title_does_not_certify_zero_clinicians(self):
        self.save(self.document(unknown=True))
        result=merge(self.source,self.maps,self.out)
        self.assertEqual(result['additional_geolocated_clinical_business_lower_bound'],0)
        self.assertEqual(result['clinically_complete_eligible_sources'],0)
        self.assertEqual(result['unresolved_contenders'],498)

    def test_remote_google_business_not_counted_in_local_fsa(self):
        self.save(self.document(remote=True))
        with self.assertRaisesRegex(RuntimeError,'outside five-kilometre'):
            merge(self.source,self.maps,self.out)

    def test_missing_tile_cannot_certify(self):
        record=self.document()
        record['complete_tiles'].pop(next(iter(TILE_KEYS)))
        self.save(record)
        result=merge(self.source,self.maps,self.out)
        self.assertEqual(result['rechecked_sources_fully_clinical'],0)

    def test_unproven_google_category_is_not_clinical_evidence(self):
        record=self.document(unknown=True)
        record['local_places'][0]['google_business_category']='Psychotherapist'
        self.save(record)
        result=merge(self.source,self.maps,self.out)
        self.assertEqual(result['additional_geolocated_clinical_business_lower_bound'],0)

if __name__=='__main__':
    unittest.main()
