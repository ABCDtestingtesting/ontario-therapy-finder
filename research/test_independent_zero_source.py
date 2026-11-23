"""Fail-closed regressions for independently rechecked Google clinical ranking."""
import unittest
from research.finalize_full_google_498 import clinical_title_classification
from research.verify_zero_google_coverage import summarize, EXPECTED_KEYS, needs_new_map_observation
from research.merge_google_checkpoints import required_base_tile_keys


class IndependentZeroSourceTests(unittest.TestCase):
    def test_search_key_count_and_scope_are_fixed(self):
        self.assertEqual(len(EXPECTED_KEYS),27)
        self.assertEqual(len(required_base_tile_keys()),18)

    def test_nonpsychotherapy_counselling_is_not_a_clinical_competitor(self):
        self.assertEqual(clinical_title_classification({
            'name':'International Career Counselling Centre Inc'}),'nonclinical')
        self.assertEqual(clinical_title_classification({
            'name':'Credit Counselling Bureau'}),'nonclinical')
        self.assertEqual(clinical_title_classification({
            'name':'Lecuyer Counselling'}),'ambiguous')
        self.assertEqual(clinical_title_classification({
            'name':'Zain Abideen Psychotherapy'}),'clinical')
        self.assertEqual(clinical_title_classification({
            'name':'Lecuyer Counselling','google_business_category':'Counselor'}),'clinical')

    def test_peer_support_or_mental_health_advocacy_is_not_proven_psychotherapy(self):
        self.assertEqual(clinical_title_classification({
            'name':'Black Mental Health Canada'}),'ambiguous')
        self.assertEqual(clinical_title_classification({
            'name':'Boots on the Ground',
            'google_business_category':'Mental health service'}),'ambiguous')
        self.assertEqual(clinical_title_classification({
            'name':'Caravan Therapy',
            'google_business_category':'Psychotherapist'}),'clinical')
        self.assertEqual(clinical_title_classification({
            'name':'Registered Social Worker'}),'ambiguous')

    def sample(self):
        return {'fsa':'L9E','observations':{},'status':'in_progress'}

    def tile(self):
        return {'status':'observed','capped':False,'unresolved':[],
                'map_area_search_verified':True,'places':[]}

    def test_capped_observed_query_needs_changed_scope_not_identical_retry(self):
        capped=self.tile()
        capped['capped']=True
        self.assertFalse(needs_new_map_observation(capped))
        capped['status']='observed_partial'
        self.assertFalse(needs_new_map_observation(capped))
        capped['map_area_search_verified']=False
        self.assertTrue(needs_new_map_observation(capped))
        uncapped=self.tile()
        self.assertFalse(needs_new_map_observation(uncapped))
        uncapped['unresolved']=[{'url':'https://www.google.com/maps/place/test'}]
        self.assertTrue(needs_new_map_observation(uncapped))
        self.assertTrue(needs_new_map_observation(None))

    def test_cap_never_certifies_empty_area(self):
        doc=self.sample()
        doc['observations']={key:self.tile() for key in EXPECTED_KEYS}
        next(iter(doc['observations'].values()))['capped']=True
        summarize(doc)
        self.assertEqual(doc['status'],'crosscheck_incomplete')
        self.assertEqual(doc['unique_local_google_businesses'],0)
        self.assertEqual(len(doc['unverified_searches']),1)

    def test_every_end_marker_still_does_not_establish_no_therapists(self):
        doc=self.sample()
        doc['observations']={key:self.tile() for key in EXPECTED_KEYS}
        summarize(doc)
        self.assertEqual(doc['status'],'all_27_independent_google_feeds_observed')
        self.assertEqual(doc['unique_local_google_businesses'],0)
        self.assertEqual(doc['clinical_title_confirmed'],0)

    def test_real_local_practitioner_supersedes_original_zero(self):
        doc=self.sample()
        doc['observations']={key:self.tile() for key in EXPECTED_KEYS}
        first=next(iter(doc['observations'].values()))
        first['places']=[{'key':'google:office123','name':'Zain Abideen Psychotherapy',
                          'lat':43.5248,'lon':-79.8147,'source_url':'https://www.google.com/maps/place/'},
                         {'key':'google:career456','name':'International Career Counselling Centre Inc',
                          'lat':43.4895,'lon':-79.7416,'source_url':'https://www.google.com/maps/place/'}]
        summarize(doc)
        self.assertEqual(doc['unique_local_google_businesses'],2)
        self.assertEqual(doc['clinical_title_confirmed'],1)
        self.assertEqual(doc['nonclinical_title_confirmed'],1)


if __name__=='__main__':
    unittest.main()
