"""Local regressions for Google-only Ontario therapy competition evidence."""
import unittest
from research.scan_all_maps import global_place_coordinates,distance_km,score_links
from research.build_google_database import repair_coordinates
from research.finalize_google_top60 import place_key
class GoogleResearchTests(unittest.TestCase):
    def test_global_us_coordinates_not_unknown(self):
        url='https://www.google.com/maps/place/Example/data=!8m2!3d37.2864131!4d-121.9429559'
        self.assertEqual(global_place_coordinates(url),(37.2864131,-121.9429559))
    def test_original_ontario_place_coordinates(self):
        url='https://www.google.com/maps/place/Example/data=!8m2!3d43.712959!4d-80.989089'
        self.assertEqual(global_place_coordinates(url),(43.712959,-80.989089))
    def test_postcode_results_keep_remote_places_out_of_five_km(self):
        local='https://www.google.com/maps/place/L/data=!8m2!3d43.713!4d-80.989'
        remote='https://www.google.com/maps/place/R/data=!8m2!3d38.9!4d-77.1'
        places,missing,outside=score_links([
            {'name':'L','url':local,'coordinates':None},
            {'name':'R','url':remote,'coordinates':None}],(43.712959,-80.989089))
        self.assertEqual(len(places),1)
        self.assertEqual(len(missing),0)
        self.assertEqual(outside,1)
    def test_recover_existing_ontario_results_and_mark_us_remote(self):
        row={'fsa':'N4W','status':'unresolved','center':[43.712959,-80.989089],
             'local_count':1,'outside_5km':0,
             'locations':[{'name':'Clinic','lat':43.713,'lon':-80.989,'url':'https://maps.example/'}],
             'unlocated_links':[{'name':'Remote','url':'https://www.google.com/maps/place/R/data=!8m2!3d38.9!4d-77.1'}]}
        cleaned=repair_coordinates(row)
        self.assertEqual(cleaned['status'],'observed')
        self.assertEqual(cleaned['unlocated_count'],0)
        self.assertEqual(cleaned['local_count'],1)
        self.assertEqual(cleaned['outside_5km'],1)
    def test_unresolved_without_coordinates_stays_unverified(self):
        row={'center':[43.7,-80.98],'status':'unresolved','locations':[],
             'unlocated_links':[{'url':'https://maps.google.com/place/NoCoordinates','name':'Unknown'}]}
        clean=repair_coordinates(row)
        self.assertEqual(clean['status'],'unresolved')
        self.assertEqual(clean['unlocated_count'],1)
    def test_same_google_place_id_dedupes_search_queries(self):
        a={'name':'A','lat':43.7,'lon':-80.9,
            'source_url':'https://google.com/maps/place/A/data=!1s0xabcd:0x1234!8m2!3d43.7!4d-80.9'}
        b={'name':'B','lat':43.700001,'lon':-80.90001,
            'source_url':'https://google.com/maps/place/B/data=!1s0xabcd:0x1234!8m2!3d43.7!4d-80.9'}
        self.assertEqual(place_key(a),place_key(b))
if __name__=='__main__':unittest.main()
