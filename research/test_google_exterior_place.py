"""Exact-place exterior exception regression tests."""
import copy
import unittest
from research.review_google_exterior_place import (
    PLACE_KEY, PLACE_NAME, adjudicate_n0l)


class ExteriorGoogleTests(unittest.TestCase):
    def sample(self):
        keys=[
            'map_movement_v7_checkbox_on|'+'|'.join(map(str,(n,e,0,t)))
            for n in (-3.4,0.,3.4) for e in (-3.4,0.,3.4)
            for t in ('psychotherapist','psychologist')]
        tiles={k:{'status':'observed','capped':False,
                  'map_area_search_verified':True,'unresolved':[]}
               for k in keys}
        tiles[keys[0]]['unresolved']=[{
            'name':PLACE_NAME,
            'url':'https://www.google.com/maps/place/Cindy+Machado/data=!1s'+PLACE_KEY}]
        return {'fsa':'N0L','status':'coordinates_unresolved','complete_tiles':tiles,
                'pending':[],'capped_leaf_tiles':0,'unresolved_leaf_links':1,
                'local_places':[],'unique_observed_local_places':0}

    def test_exact_exterior_place_is_source_annotated_without_hiding_original(self):
        data=self.sample()
        reviewed=adjudicate_n0l(data)
        self.assertEqual(reviewed['status'],'verified_local_tiles_with_exterior_exception')
        self.assertEqual(reviewed['unresolved_leaf_links'],1)
        self.assertEqual(len(reviewed['externally_verified_exterior_links']),1)
        self.assertIn(PLACE_KEY,reviewed['externally_verified_exterior_links'][0]['google_source_url'])

    def test_different_place_identity_never_excluded(self):
        data=self.sample()
        link=next(x for t in data['complete_tiles'].values() for x in t['unresolved'])
        link['name']='Different Therapist'
        self.assertEqual(adjudicate_n0l(data)['status'],'coordinates_unresolved')

    def test_missing_geographic_evidence_or_capping_prevents_exception(self):
        data=self.sample()
        data['capped_leaf_tiles']=1
        self.assertEqual(adjudicate_n0l(data)['status'],'coordinates_unresolved')
        data=self.sample()
        next(iter(data['complete_tiles'].values()))['map_area_search_verified']=False
        self.assertEqual(adjudicate_n0l(data)['status'],'coordinates_unresolved')


if __name__=='__main__':
    unittest.main()
