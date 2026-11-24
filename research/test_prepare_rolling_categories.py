"""Protect clinical Google source categories across successive top-60 shortlists."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.prepare_google_title_uncertainties import prepare

class RollingGoogleCategoryPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'source.json'
        self.ranking=self.root/'provisional.csv'
        self.last=self.root/'last'
        self.last.mkdir()
        self.out=self.root/'new'
        self.areas=[f'{prefix}{digit}{letter}' for prefix in 'KLMNP'
                    for digit in '0123456789'
                    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'][:498]
        self.places={fsa:[] for fsa in self.areas}
        self.places[self.areas[0]]=[{
            'key':'therapist-1',
            'name':'Community Wellness',
            'lat':43.01,'lon':-79.01,
            'source_url':'https://www.google.com/maps/place/Wellness'}]
        self.source.write_text(json.dumps({'all_places_by_fsa':self.places}))
        with self.ranking.open('w',newline='') as fh:
            w=csv.DictWriter(fh,fieldnames=['fsa',
                'firstpass_title_confirmed_clinical_places',
                'firstpass_ambiguous_business_titles'])
            w.writeheader()
            for code in self.areas[:60]:
                w.writerow({'fsa':code,
                    'firstpass_title_confirmed_clinical_places':0,
                    'firstpass_ambiguous_business_titles':int(code==self.areas[0])})

    def store_prior(self,place):
        (self.last/(self.areas[0]+'.json')).write_text(json.dumps({
            'fsa':self.areas[0],'local_places':[place]}))

    def test_previously_verified_business_detail_survives_a_new_candidate_plan(self):
        prior=dict(self.places[self.areas[0]][0])
        prior.update({'google_business_category':'Psychotherapist',
            'google_category_checked_at':'2026-11-24T01:00:00Z',
            'google_category_evidence_url':'https://www.google.com/maps/place/Wellness'})
        self.store_prior(prior)
        result=prepare(self.source,self.ranking,self.out,self.last)
        self.assertEqual(result['candidate_fsas_reusing_previous_checkpoints'],1)
        saved=json.loads((self.out/'checkpoints'/(self.areas[0]+'.json')).read_text())
        self.assertEqual(saved['local_places'][0]['google_business_category'],'Psychotherapist')

    def test_old_missing_categories_must_be_retried(self):
        prior=dict(self.places[self.areas[0]][0])
        prior['google_category_checked_at']='2026-11-24T01:00:00Z'
        self.store_prior(prior)
        prepare(self.source,self.ranking,self.out,self.last)
        saved=json.loads((self.out/'checkpoints'/(self.areas[0]+'.json')).read_text())
        self.assertNotIn('google_category_checked_at',saved['local_places'][0])

    def test_previous_place_identity_change_must_fail(self):
        prior=dict(self.places[self.areas[0]][0])
        prior['lat']=43.99
        self.store_prior(prior)
        with self.assertRaisesRegex(RuntimeError,'changed identity'):
            prepare(self.source,self.ranking,self.out,self.last)

    def test_invalid_clinical_category_without_google_proof_must_fail(self):
        prior=dict(self.places[self.areas[0]][0])
        prior['google_business_category']='Psychotherapist'
        self.store_prior(prior)
        with self.assertRaisesRegex(RuntimeError,'no Google detail-page proof'):
            prepare(self.source,self.ranking,self.out,self.last)

if __name__=='__main__':
    unittest.main()
