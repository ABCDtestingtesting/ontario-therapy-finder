"""Incomplete Google feeds preserve real local place links, never certify zeros."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finder.common import HumanVerificationRequired, SourceUnavailable
from research.recover_google_tiles import scan_tile, run_area


class PartialSourceLowerBoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.center = (43.711, -79.570)

    def unverified_feed(self, context, query, lat, lon, diagnostic, **kwargs):
        diagnostic.mkdir(parents=True, exist_ok=True)
        evidence = {
            'query': query,
            'search_url': 'https://www.google.com/maps/search/example',
            'place_links': [{
                'url': 'https://www.google.com/maps/place/Valid+Psychotherapy/'
                       'data=!8m2!3d43.711!4d-79.570',
                'name': 'Valid Psychotherapy',
                'coordinates': [43.711, -79.570],
            }],
            'completed': False,
            'geographic_refresh_verified': True,
            'completion_reason': None,
            'failure': 'Missing verified Google end-of-list marker',
        }
        (diagnostic / 'search_evidence.json').write_text(json.dumps(evidence))
        raise SourceUnavailable('Google result list still loading')

    def test_partial_feed_is_observed_but_explicitly_uncertified(self):
        with patch('research.recover_google_tiles.scan_one',
                   side_effect=self.unverified_feed):
            result = scan_tile(None,'M9M',self.center,0.,0.,0.,
                               'psychotherapist',self.root)
        self.assertEqual(result['status'], 'observed_partial')
        self.assertTrue(result['capped'])
        self.assertEqual(len(result['places']),1)
        self.assertIsNone(result['reason'])

    def test_partial_listing_remains_pending_for_future_resume(self):
        area={'fsa':'M9M','lat':43.711,'lon':-79.570,'population_2021':20000}
        def partial(*args):
            return {'status':'observed_partial','places':[{
                 'key':'google:1','name':'Valid Psychotherapy',
                 'source_url':'https://www.google.com/maps/place/ValidPsychotherapy',
                 'lat':43.711,'lon':-79.570}],
                 'capped':True,'unresolved':[]}
        with patch('research.recover_google_tiles.scan_tile',side_effect=partial):
            r=run_area(None,area,self.root,180)
        self.assertEqual(r['unique_observed_local_places'],1)
        self.assertEqual(len(r['pending']),18)
        self.assertEqual(r['status'],'coverage_incomplete')

    def test_human_verification_never_becomes_partial_success(self):
        with patch('research.recover_google_tiles.scan_one',
                   side_effect=HumanVerificationRequired('Google challenge')):
            with self.assertRaises(HumanVerificationRequired):
                scan_tile(None,'M9M',self.center,0.,0.,0.,
                          'psychotherapist',self.root)


if __name__ == '__main__':
    unittest.main()
