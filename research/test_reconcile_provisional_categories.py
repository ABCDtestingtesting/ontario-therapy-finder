"""Protect 498-area rankings against category-evidence corruption."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.reconcile_provisional_google_categories import run


class ClinicalCategoryReconciliationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder=Path(temp.name)
        self.base=self.folder/'full.csv'
        self.raw=self.folder/'original.json'
        self.plan=self.folder/'plan.json'
        self.categories=self.folder/'categories'
        self.categories.mkdir()
        self.out=self.folder/'result'
        self.codes=[f'{prefix}{digit}{letter}' for prefix in 'KLMNP' for digit in '0123456789' for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'][:498]
        with self.base.open('w',newline='') as fh:
            fields=['fsa','population_5km_estimate_2021','confirmed_clinical_business_lower_bound',
                    'clinically_audited_source_complete','excluded_last_90_days',
                    'clinical_businesses_per_10000_lower_bound']
            wr=csv.DictWriter(fh,fieldnames=fields)
            wr.writeheader()
            wr.writerows({'fsa':code,'population_5km_estimate_2021':10000,
                          'confirmed_clinical_business_lower_bound':0,
                          'clinically_audited_source_complete':'False',
                          'excluded_last_90_days':'False',
                          'clinical_businesses_per_10000_lower_bound':0}
                         for code in self.codes)
        self.original={code:[] for code in self.codes}
        self.original['K0A']=[{'key':'p1','name':'Community Wellness',
                'lat':43.5,'lon':-79.5,'source_url':'https://www.google.com/maps/place/a'}]
        self.raw.write_text(json.dumps({'all_places_by_fsa':self.original}))
        self.plan.write_text(json.dumps({'fsas':[{'fsa':c} for c in self.codes[:60]]}))

    def store(self,places,code='K0A'):
        (self.categories/(code+'.json')).write_text(json.dumps(
            {'fsa':code,'local_places':places}))

    def test_verified_clinical_category_refines_lower_bound_and_still_blocks_false_certification(self):
        self.store([{**self.original['K0A'][0],
                     'google_business_category':'Psychotherapist',
                     'google_category_evidence_url':'https://www.google.com/maps/place/a'}])
        report=run(self.base,self.raw,self.plan,self.categories,self.out)
        self.assertEqual(report['new_positively_identified_clinical_fsa_count'],1)
        self.assertEqual(report['additional_verified_clinical_lower_bound_places'],1)
        self.assertFalse(report['final_60_source_model_certified'])
        self.assertFalse((self.out/'Ontario_Certified_60_Within_Google_Observation_Model.csv').exists())
        with (self.out/'Ontario_498_After_Primary_Category_Checks.csv').open() as fh:
            rows={r['fsa']:r for r in csv.DictReader(fh)}
        self.assertEqual(rows['K0A']['confirmed_clinical_business_lower_bound'],'1')
        self.assertEqual(rows['K0A']['clinician_absence_proven'],'False')

    def test_google_category_lookup_cannot_change_original_place_coordinates(self):
        self.store([{**self.original['K0A'][0], 'lat':42.0}])
        with self.assertRaisesRegex(RuntimeError,'changed original place'):
            run(self.base,self.raw,self.plan,self.categories,self.out)

    def test_unknown_category_source_fsa_is_rejected(self):
        self.store([],code='P0Z')
        with self.assertRaisesRegex(RuntimeError,'unauthorized candidate'):
            run(self.base,self.raw,self.plan,self.categories,self.out)

    def test_zero_category_artifacts_remain_uncertain(self):
        report=run(self.base,self.raw,self.plan,self.categories,self.out)
        self.assertEqual(len(report['provisional_60_category_fsa_missing']),60)
        self.assertFalse(report['final_60_source_model_certified'])


if __name__=='__main__':
    unittest.main()
