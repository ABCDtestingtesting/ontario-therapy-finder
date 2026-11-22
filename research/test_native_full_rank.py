"""End-to-end native Google evidence gate on a synthetic 498-FSA census."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.finalize_full_google_498 import combine
from research.native_google_nine import NINE


class CompleteOntarioRankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        fsas = [a+str(d)+chr(c) for a in 'KLMNP' for d in range(10)
                for c in range(65,91)]
        codes = list(NINE)+[x for x in fsas if x not in NINE][:489]
        self.assertEqual(len(codes),498)
        self.audit=self.root/'first.csv'
        fields=['fsa','status','feed_capped','unlocated_links',
                'population_5km_estimate','google_observed_5km',
                'previous_90_days','latitude','longitude','source_url']
        with self.audit.open('w',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=fields)
            writer.writeheader()
            for i,code in enumerate(codes):
                verified=9<=i<69
                writer.writerow({
                    'fsa':code,'status':'confirmed_observed_feed' if verified else 'capped_feed',
                    'feed_capped':'False' if verified else 'True',
                    'unlocated_links':0,'population_5km_estimate':10000 if i<9 else (8000 if verified else 1000),
                    'google_observed_5km':0 if i<9 else (1 if verified else 10),
                    'previous_90_days':'False','latitude':'44.0',
                    'longitude':'-79.0','source_url':'https://google.com/maps/search/test'
                })
        self.recovery=self.root/'recovery'
        self.recovery.mkdir()
        self.native=self.root/'native'
        self.native.mkdir()
        self.out=self.root/'out'

    def make_nine(self,status='grid_observed_complete'):
        for code in NINE:
            root=self.native/code
            root.mkdir()
            record={'fsa':code, 'status':status,'process_returncode':0,
                    'raw_rows':40,'bad_coordinates':[],
                    'unique_clinical_local_places':1,
                    'raw_csv_sha256':'0123456789abcdef'}
            (root/'native_evidence.json').write_text(json.dumps(record))

    def test_exact_498_and_complete_native_coverage_certifies_top_60(self):
        self.make_nine()
        report=combine(self.audit,self.recovery,self.out,self.native)
        self.assertTrue(report['google_60_certified_within_source_observation_model'])
        self.assertEqual(report['total_ontario_fsa'],498)
        self.assertEqual(report['independent_google_grid_source_complete'],9)
        with (self.out/'Ontario_Google_Best_60_Across_498.csv').open() as file:
            certified=list(csv.DictReader(file))
        self.assertEqual(len(certified),60)
        self.assertTrue(all(item['completed_source_feed']=='True' for item in certified))

    def test_partial_native_scan_is_not_certification(self):
        self.make_nine('partial_native')
        with self.assertRaisesRegex(RuntimeError,'incompletely observed'):
            combine(self.audit,self.recovery,self.out,self.native)
        self.assertFalse((self.out/'Ontario_Google_Best_60_Across_498.csv').exists())

    def test_missing_independent_sources_fail_gate(self):
        with self.assertRaisesRegex(RuntimeError,'incompletely observed'):
            combine(self.audit,self.recovery,self.out,self.native)


if __name__=='__main__':
    unittest.main()
