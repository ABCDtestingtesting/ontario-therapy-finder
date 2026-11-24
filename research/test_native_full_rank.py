"""End-to-end native Google evidence gate on a synthetic 498-FSA census."""
import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from research.finalize_full_google_498 import combine, independent_grid_empty_evidenced
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
        self.codes = codes
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

    def make_sixty_real_clinical_source_feeds(self):
        # Exact completed feeds are permitted only with actual clinical
        # business evidence. Other 429 sources have a sufficiently strong
        # clinical lower bound to be rank dominated despite incomplete feeds.
        for i,code in enumerate(self.codes):
            if i < 9:
                continue
            number = 1 if i < 69 else 10
            row = {
                'fsa':code,
                'status':'verified_tile_feed' if i < 69 else 'observed_capped',
                'unique_observed_local_places':number,
                'local_places':[{'key':f'{code}-source-{j}',
                    'name':f'Example {j} Psychotherapy',
                    'lat':44.0,'lon':-79.0,
                    'source_url':'https://www.google.com/maps/place/example'} for j in range(number)],
                'capped_leaf_tiles':0 if i < 69 else 1,
                'pending':[],'unresolved_leaf_links':0
            }
            row['complete_tiles']={
                'map_movement_v7_checkbox_on|'+'|'.join(map(str,(n,e,0,term))): {
                    'status':'observed','map_area_search_verified':True,
                    'geographic_result_scope_verified':True,
                    'visible_links':1,'capped':False,'unresolved':[],
                    'places':row['local_places'][:1], 'reason':'visible_end_of_list'}
                for n in (-3.4,0.0,3.4) for e in (-3.4,0.0,3.4)
                for term in ('psychotherapist','psychologist')}
            (self.recovery/(code+'.json')).write_text(json.dumps(row))

    def test_exact_498_and_complete_native_coverage_certifies_top_60(self):
        self.make_nine()
        self.make_sixty_real_clinical_source_feeds()
        with patch('research.finalize_full_google_498.independent_grid_searches_complete',return_value=True):
            report=combine(self.audit,self.recovery,self.out,self.native)
        self.assertTrue(report['google_60_certified_within_source_observation_model'])
        self.assertEqual(report['total_ontario_fsa'],498)
        self.assertEqual(report['independent_google_grid_source_complete'],9)
        self.assertEqual(report['recovery_source_complete'],60)
        self.assertEqual(report['first_pass_complete'],0)
        self.assertEqual(report['historical_complete_keyword_only_business_feeds'],60)
        with (self.out/'Ontario_Google_Best_60_Across_498.csv').open() as file:
            certified=list(csv.DictReader(file))
        self.assertEqual(len(certified),60)
        self.assertTrue(all(item['completed_source_feed']=='True' for item in certified))

    def test_60_keyword_only_feeds_never_certify_therapist_counts(self):
        self.make_nine()
        with patch('research.finalize_full_google_498.independent_grid_searches_complete',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'incompletely observed'):
                combine(self.audit,self.recovery,self.out,self.native)
        self.assertFalse((self.out/'Ontario_Google_Best_60_Across_498.csv').exists())
        with (self.out/'google_498_recovery_report.json').open() as fh:
            result=json.load(fh)
        self.assertEqual(result['clinically_completed_eligible_fsa'],9)
        self.assertEqual(result['historical_complete_keyword_only_business_feeds'],60)
        self.assertIsNone(result['top_60_cutoff_observed_google_listings_per_10000_residents'])

    def test_original_real_places_raise_lower_bound_but_do_not_complete_source(self):
        verified_csv=self.root/'original_google_verified.csv'
        fields=['fsa','firstpass_clinical_title_lower_bound','firstpass_ambiguous_titles',
                'firstpass_nonclinical_titles','original_google_located_businesses',
                'firstpass_source_shard_sha256']
        with verified_csv.open('w',newline='') as fh:
            wr=csv.DictWriter(fh,fieldnames=fields);wr.writeheader()
            for code in self.codes:
                count=3 if code==self.codes[100] else 0
                wr.writerow({'fsa':code,'firstpass_clinical_title_lower_bound':count,
                    'firstpass_ambiguous_titles':0,'firstpass_nonclinical_titles':0,
                    'original_google_located_businesses':count,
                    'firstpass_source_shard_sha256':'a'*64})
        with self.assertRaisesRegex(RuntimeError,'incompletely observed'):
            combine(self.audit,self.recovery,self.out,self.native,verified_csv)
        with (self.out/'ontario_498_google_recovery_audit.csv').open() as fh:
            results={r['fsa']:r for r in csv.DictReader(fh)}
        self.assertEqual(results[self.codes[100]]['google_observed_therapy_locations_lower_bound'],'3')
        self.assertEqual(results[self.codes[100]]['original_google_clinical_title_lower_bound'],'3')
        self.assertEqual(results[self.codes[100]]['completed_source_feed'],'False')
        summary=json.loads((self.out/'google_498_recovery_report.json').read_text())
        self.assertEqual(summary['original_item_level_clinical_source_fsa_count'],498)
        self.assertEqual(summary['original_item_level_clinical_lower_bound_total'],3)
        self.assertFalse(summary['google_60_certified_within_source_observation_model'])

    def test_originally_observed_clinic_missing_from_complete_new_source_blocks_certification(self):
        self.make_nine()
        self.make_sixty_real_clinical_source_feeds()
        # A high-population FSA with two confirmed clinics can still
        # beat the 60th verified area; its missing source must remain pending.
        with self.audit.open(newline='') as fh:
            original_rows=list(csv.DictReader(fh))
        next(r for r in original_rows if r['fsa']==self.codes[9])['population_5km_estimate']='100000'
        with self.audit.open('w',newline='') as fh:
            wr=csv.DictWriter(fh,fieldnames=list(original_rows[0]));wr.writeheader();wr.writerows(original_rows)
        evidence=self.root/'firstpass_item_evidence.csv'
        fields=['fsa','firstpass_clinical_title_lower_bound','firstpass_ambiguous_titles',
                'firstpass_nonclinical_titles','original_google_located_businesses',
                'firstpass_source_shard_sha256']
        with evidence.open('w',newline='') as fh:
            wr=csv.DictWriter(fh,fieldnames=fields);wr.writeheader()
            for code in self.codes:
                count=2 if code==self.codes[9] else 0
                wr.writerow({'fsa':code,'firstpass_clinical_title_lower_bound':count,
                    'firstpass_ambiguous_titles':0,'firstpass_nonclinical_titles':0,
                    'original_google_located_businesses':count,
                    'firstpass_source_shard_sha256':'a'*64})
        with patch('research.finalize_full_google_498.independent_grid_searches_complete',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'incompletely observed'):
                combine(self.audit,self.recovery,self.out,self.native,evidence)
        rows={r['fsa']:r for r in csv.DictReader(
            (self.out/'ontario_498_google_recovery_audit.csv').open())}
        self.assertEqual(rows[self.codes[9]]['google_observed_therapy_locations_lower_bound'],'2')
        self.assertEqual(rows[self.codes[9]]['completed_source_feed'],'False')
        report=json.loads((self.out/'google_498_recovery_report.json').read_text())
        self.assertEqual(report['clinically_completed_eligible_fsa'],68)
        self.assertFalse(report['google_60_certified_within_source_observation_model'])

    def test_duplicate_or_incomplete_original_clinical_sources_fail_closed(self):
        source=self.root/'broken.csv'
        source.write_text('fsa,firstpass_clinical_title_lower_bound\\nK0A,1\\n')
        with self.assertRaisesRegex(RuntimeError,'498 distinct'):
            combine(self.audit,self.recovery,self.out,self.native,source)

    def test_partial_native_scan_is_not_certification(self):
        self.make_nine('partial_native')
        with self.assertRaisesRegex(RuntimeError,'incompletely observed'):
            combine(self.audit,self.recovery,self.out,self.native)
        self.assertFalse((self.out/'Ontario_Google_Best_60_Across_498.csv').exists())

    def test_missing_native_csv_and_reported_places_cannot_prove_zero(self):
        folder=self.native/'L0B'
        folder.mkdir()
        (folder/'native_evidence.json').write_text('{}')
        south, west, north, east = 42.3, -82.3, 42.394, -82.174
        cell=2.1
        terms=['psychotherapist','psychologist','counselling therapy','mental health clinic']
        (folder/'run_plan.json').write_text(json.dumps({
            'bbox':f'{south},{west},{north},{east}',
            'grid_cell_km':cell,'terms':terms}))
        rows=math.ceil((north-south)/(cell/111.32))
        cols=math.ceil((east-west)/(cell/(111.32*math.cos(math.radians((south+north)/2)))))
        events=[]
        for term in terms:
            for i in range(rows):
                for j in range(cols):
                    lat=south+(i+.5)*(north-south)/rows
                    lon=west+(j+.5)*(east-west)/cols
                    url=f'https://www.google.com/maps/search/{term.replace(" ","%20")}/@{lat:.6f},{lon:.6f},16z'
                    events.append(json.dumps({'message':'job finished','status':'success',
                         'job':f'Job{{ID: abc, Method: GET, URL: {url}, UrlParams: map[hl:en]}}'}))
        events.append(json.dumps({'message':'18 places found'}))
        events.append(json.dumps({'message':'scrapemate exited'}))
        log=folder/'collector.log'
        log.write_text('\n'.join(events)+'\n')
        meta={'process_returncode':0,'source_empty_or_missing':True,'raw_rows':None}
        self.assertFalse(independent_grid_empty_evidenced(meta,folder/'native_evidence.json'))
        log.write_text('\n'.join(events[:-2]+events[-1:])+'\n')
        self.assertFalse(independent_grid_empty_evidenced(meta,folder/'native_evidence.json'))
        meta['process_returncode']=124
        self.assertFalse(independent_grid_empty_evidenced(meta,folder/'native_evidence.json'))

    def test_valid_498_source_audit_can_succeed_without_false_top60_certification(self):
        # The audit has distinct failure and publication states.
        report=combine(self.audit,self.recovery,self.out,self.native,
                       allow_uncertified_audit=True)
        self.assertEqual(report['total_ontario_fsa'],498)
        self.assertFalse(report['google_60_certified_within_source_observation_model'])
        self.assertEqual(report['clinically_completed_eligible_fsa'],0)
        self.assertFalse((self.out/'Ontario_Google_Best_60_Across_498.csv').exists())
        self.assertTrue((self.out/'ontario_498_google_recovery_audit.csv').exists())

    def test_missing_independent_sources_fail_gate(self):
        with self.assertRaisesRegex(RuntimeError,'incompletely observed'):
            combine(self.audit,self.recovery,self.out,self.native)


if __name__=='__main__':
    unittest.main()
