import unittest,tempfile,csv
from pathlib import Path
from integrated_run import finalize,ROOT,write
class CombinedTest(unittest.TestCase):
    def test_full_direct_and_missing_search_stays_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);p=out/"decision-live-evidence";p.mkdir()
            with (ROOT/"candidates.csv").open() as f:areas=list(csv.DictReader(f))
            state={r["fsa"]:{"status":"complete","pages":[{"page":1,"ids":[str(10000+i)],"next_page":None,"directory_label":"<10"}]} for i,r in enumerate(areas)}
            write(p/"pages.json",state);write(p/"status.json",{"full_live_verification":True})
            report=finalize(out,2030,{"browser":0,"index":3,"named":3})
            self.assertTrue(report["direct_page_chains_verified"])
            self.assertFalse(report["completed_within_target"])
            with (out/"weekly-ranking.csv").open() as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),60);self.assertEqual(rows[0]["fsa"],"L7A")
            state[areas[0]["fsa"]]["pages"][0]["next_page"]=2
            write(p/"pages.json",state)
            report=finalize(out,2030,{"browser":0,"index":3,"named":3})
            self.assertEqual(report["direct_areas_completed"],59)
            self.assertFalse(report["direct_page_chains_verified"])
if __name__=="__main__":unittest.main()
