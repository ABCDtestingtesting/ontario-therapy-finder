"""Regression checks for restoring actual item-level Google business evidence."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.validate_firstpass_place_evidence import parse_sources


class OriginalGooglePlaceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder=Path(tmp.name)
        self.sources=self.folder/'shards'
        self.sources.mkdir()
        self.baseline=self.folder/'baseline.csv'
        self.codes=[f'K{i:03d}' for i in range(498)]
        with self.baseline.open('w',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=['fsa','latitude','longitude'])
            writer.writeheader()
            writer.writerows({'fsa':code,'latitude':43.5,'longitude':-79.5} for code in self.codes)
        self.shards={}
        for shard in range(44):
            rows=[]
            for code in self.codes[shard::44]:
                rows.append({'fsa':code,'center':[43.5,-79.5],
                  'status':'observed','search_query':f'psychotherapist near {code} Ontario Canada',
                  'local_count':0,'locations':[],'feed_capped':False})
            path=self.sources/f'shard-{shard:02d}'
            path.mkdir()
            self.shards[shard]=rows
        self.flush()

    def flush(self):
        for shard,rows in self.shards.items():
            (self.sources/f'shard-{shard:02d}'/'results.json').write_text(json.dumps({'rows':rows}))

    def record(self,code):
        return next(row for rows in self.shards.values() for row in rows if row['fsa']==code)

    def test_498_distinct_source_records_and_exact_location_category_partition(self):
        row=self.record('K000')
        row['locations']=[
          {'name':'Test Psychotherapy','lat':43.5,'lon':-79.5,
           'url':'https://www.google.com/maps/place/Test+Psychotherapy'},
          {'name':'Credit Counselling Office','lat':43.5,'lon':-79.5003,
           'url':'https://www.google.com/maps/place/Credit+Counselling'},
          {'name':'Community Wellness','lat':43.5,'lon':-79.501,
           'url':'https://www.google.com/maps/place/Community+Wellness'}]
        row['local_count']=3
        self.flush()
        records,details=parse_sources(self.sources,self.baseline)
        self.assertEqual(len(records),498)
        self.assertEqual(records['K000']['firstpass_clinical_title_lower_bound'],1)
        self.assertEqual(records['K000']['firstpass_nonclinical_titles'],1)
        self.assertEqual(records['K000']['firstpass_ambiguous_titles'],1)
        self.assertEqual(details['K000'][0]['name'],'Test Psychotherapy')
        self.assertFalse(records['K000']['clinician_absence_verified'])

    def test_failed_source_is_retained_as_uncertain_empty(self):
        row=self.record('K001')
        row['status']='incomplete'
        row.pop('search_query')
        self.flush()
        records,_=parse_sources(self.sources,self.baseline)
        self.assertEqual(records['K001']['original_source_status'],'incomplete')
        self.assertEqual(records['K001']['firstpass_clinical_title_lower_bound'],0)
        self.assertFalse(records['K001']['clinician_absence_verified'])

    def test_wrong_map_coordinates_are_fatal(self):
        self.record('K002')['center']=[44.5,-79.5]
        self.flush()
        with self.assertRaisesRegex(RuntimeError,'centre mismatch'):
            parse_sources(self.sources,self.baseline)

    def test_unverified_out_of_region_location_is_fatal(self):
        row=self.record('K003')
        row['locations']=[{'name':'Test Psychotherapy','lat':48.5,'lon':-79.5,
          'url':'https://www.google.com/maps/place/Distant'}]
        row['local_count']=1
        self.flush()
        with self.assertRaisesRegex(RuntimeError,'outside verified 5-km'):
            parse_sources(self.sources,self.baseline)

    def test_duplicated_fsa_across_44_shards_is_fatal(self):
        self.shards[0].append(dict(self.shards[1][0]))
        self.flush()
        with self.assertRaisesRegex(RuntimeError,'Duplicate or foreign FSA'):
            parse_sources(self.sources,self.baseline)

    def test_incomplete_source_cannot_smuggle_unverified_locations(self):
        row=self.record('K004')
        row['status']='incomplete'
        row.pop('search_query')
        row['locations']=[{'name':'Test Psychotherapy','lat':43.5,'lon':-79.5,
          'url':'https://www.google.com/maps/place/Test'}]
        row['local_count']=1
        self.flush()
        with self.assertRaisesRegex(RuntimeError,'incomplete Google source contains unverified results'):
            parse_sources(self.sources,self.baseline)


if __name__=='__main__':
    unittest.main()
