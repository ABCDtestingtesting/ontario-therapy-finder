"""Off-network regression tests of the independent Ontario Google collector."""
import csv
import tempfile
import unittest
from pathlib import Path
from research.native_google_nine import coords, category_ok, parse_places, NINE


class GoogleNativeNineTests(unittest.TestCase):
    def test_exact_nine_contenders(self):
        self.assertEqual(set(NINE), {'L4M','L1A','N7M','N1R','L4P','L9L','L0B','L0M','L7M'})

    def test_filter_rejects_unrelated_healthcare_and_recreation(self):
        for title, category in (
            ('Georgina Animal Shelter & Adoption Centre', 'Animal shelter'),
            ('C.M. Wilson Conservation Area', 'Conservation area'),
            ('Horseshoe Chiropractic', 'Chiropractor'),
            ('Local Physiotherapy', 'Physical therapy clinic'),
            ('Family Pharmacy', 'Pharmacy'),
        ):
            self.assertFalse(category_ok({'title':title,'category':category}),
                             (title,category))

    def test_clinical_query_does_not_turn_nonclinical_business_into_therapist(self):
        for title, category in (
            ('Physiotherapy & Wellness Clinic', 'Psychotherapist'),
            ('Dog Behavioural Therapy', 'Mental health service'),
            ('Sports Massage', 'Counselor'),
        ):
            self.assertFalse(category_ok({'title':title,'category':category}),
                             (title,category))

    def test_accepts_google_clinical_categories(self):
        for title, category in (
            ('X & Y Clinical Practice','Psychotherapist'),
            ('Psychological Services','Psychologist'),
            ('Mental Health Centre','Mental health service'),
            ('Community Counselling','Counselor'),
        ):
            self.assertTrue(category_ok({'title':title,'category':category}),
                            (title,category))

    def test_distinct_locations_coordinates_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.csv'
            fields=['title','category','latitude','longitude','link','place_id']
            records=[
                ['Local Psychotherapy','Psychotherapist','44.555','-79.705','https://google.com/maps/place/1','g1'],
                ['Local Psychotherapy','Psychotherapist','44.555','-79.705','https://google.com/maps/place/1','g1'],
                ['Unrelated Pharmacy','Pharmacy','44.555','-79.705','https://google.com/maps/place/2','g2'],
                ['Other Psychotherapist','Psychotherapist','45.7','-79.705','https://google.com/maps/place/3','g3'],
                ['Unlocated Psychotherapist','Psychotherapist','','','https://google.com/maps/place/4','g4'],
            ]
            with path.open('w',newline='') as fd:
                writer=csv.writer(fd);writer.writerow(fields);writer.writerows(records)
            result=parse_places(path,(44.55544,-79.704633))
            self.assertEqual(result['raw_rows'],5)
            self.assertEqual(len(result['valid_places']),1)
            self.assertEqual(result['outside_radius'],1)
            self.assertEqual(result['not_clinical'],1)
            self.assertEqual(len(result['bad_coordinates']),1)

    def test_5km_grid_covers_circle(self):
        s,w,n,e=map(float,coords((44.55544,-79.704633)).split(','))
        self.assertLess(s,44.55544);self.assertGreater(n,44.55544)
        self.assertLess(w,-79.704633);self.assertGreater(e,-79.704633)


if __name__=='__main__':
    unittest.main()
