import unittest,tempfile,csv
from pathlib import Path
from directory_index import *
class DirectoryTest(unittest.TestCase):
    def test_count_scope(self):
        self.assertEqual(extract_count("Number of Counsellors in M3N\n< 10","M3N"),"<10")
        self.assertEqual(extract_count("Number of Counsellors in M3N\n30+","M3N"),"30+")
        self.assertIsNone(extract_count("Number of Counsellors in M3L 30+","M3N"))
        self.assertFalse(exact_url(url("M3N")+"?category=adults","M3N"))
        self.assertFalse(exact_url("https://evil.example/ca/therapists/m3n","M3N"))
    def test_all_60_and_no_false_completion(self):
        def no(q):return {"results":[]}
        with tempfile.TemporaryDirectory() as t:
            rows=run(t,providers=[("freeserp",no)],delay=lambda _:None)
            self.assertEqual(len(rows),60)
            self.assertTrue(all(r["count_status"]=="historical_snapshot_only" and not r["exact_current_count_verified"] for r in rows))
            self.assertEqual(rows[0]["fsa"],"M3N")
            self.assertTrue(all(r["google"] and r["bing"] and r["duckduckgo"] and r["brave"] for r in rows))
    def test_exa_and_freeserp(self):
        q="Number of Counsellors in M3N 30+"
        self.assertEqual(extract("exa",{"content":[{"text":"Title: M3N\nURL: "+url("M3N")+"\n"+q}]},"M3N"),[("30+",None)])
        self.assertEqual(extract("freeserp",{"results":[{"url":url("M3N"),"snippet":q}]},"M3N"),[("30+",None)])
        self.assertEqual(extract("freeserp",{"results":[{"url":url("M3L"),"snippet":q}]},"M3N"),[])
if __name__=="__main__":unittest.main()
