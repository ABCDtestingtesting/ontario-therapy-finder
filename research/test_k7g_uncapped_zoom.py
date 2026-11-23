"""Safeguards for geographically verified K7G zoom-specific cap resolution."""
import unittest
from research.adjudicate_k7g_uncapped_zoom import replace_capped_tile_with_uncapped_local_recheck,K7G_KEY
from research.merge_google_checkpoints import required_base_tile_keys

def sample():
    tiles={k:{'status':'observed','capped':False,'unresolved':[],
                'map_area_search_verified':True,'places':[]}
           for k in required_base_tile_keys()}
    tiles[K7G_KEY]['capped']=True
    old={'fsa':'K7G','status':'observed_capped','complete_tiles':tiles,
         'unique_observed_local_places':0,'local_places':[],'capped_leaf_tiles':1,'pending':[]}
    tile={'code':'K7G','north_km':-3.4,'east_km':3.4,'level':1,
          'term':'psychotherapist','source_url':'https://www.google.com/maps/search/psychotherapist/@44.2450861,-76.2129949,16z?hl=en',
          'map_area_search_verified':True,'visible_links':0,'capped':False,
          'reason':'explicit_no_results','places':[],'unresolved':[],'status':'observed'}
    probe={'fsa':'K7G','query':'psychotherapist','north_km':-3.4,
           'east_km':3.4,'zoom':16,'tile':tile,
           'capped_original_14z_not_superseded':True}
    return old,probe

class K7GTests(unittest.TestCase):
    def test_real_uncapped_higher_zoom_verified_and_old_cap_preserved(self):
        old,p=sample()
        merged=replace_capped_tile_with_uncapped_local_recheck(old,p)
        self.assertEqual(merged['status'],'verified_tile_feed')
        self.assertEqual(merged['capped_leaf_tiles'],0)
        self.assertEqual(merged['complete_tiles'][K7G_KEY]['visible_links'],0)
        self.assertTrue(merged['superseded_tile_observations'][K7G_KEY][0]['capped'])
        self.assertTrue(old['complete_tiles'][K7G_KEY]['capped'])
    def test_bad_geography_or_result_cap_fails_closed(self):
        for attr,value in [('map_area_search_verified',False),('capped',True),
                           ('reason','not_proven'),('visible_links',120)]:
            old,p=sample();p['tile'][attr]=value
            with self.assertRaises(RuntimeError):
                replace_capped_tile_with_uncapped_local_recheck(old,p)
    def test_new_google_place_does_not_become_zero(self):
        old,p=sample();p['tile']['places']=[{'key':'real_clinic'}]
        with self.assertRaises(RuntimeError):
            replace_capped_tile_with_uncapped_local_recheck(old,p)
if __name__=='__main__':unittest.main()
