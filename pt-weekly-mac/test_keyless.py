import csv,datetime as dt,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import keyless_probe as k
from weekly_keyless import weekly
from release_gate import audit
ROOT=Path(__file__).resolve().parent
BASE=ROOT/"candidates.csv"
class TestKeyless(unittest.TestCase):
    def test_full_pipeline_resume_and_scoped_counts(self):
        calls=[]
        def free(q):
            calls.append(q)
            f=q.split('"')[1]
            return {"results":[{"url":"https://www.psychologytoday.com/ca/therapists/test/12345","snippet":f},{"url":"https://www.psychologytoday.com/ca/therapists/other/67890","snippet":"other"}]}
        def exa(q):
            calls.append(q)
            return {"content":[{"text":"Title: Example\nURL: https://www.psychologytoday.com/ca/therapists/test/12345\n"+q.split('"')[1]}]}
        def collector(**kwargs):
            return k.survey(**kwargs,sources=[("freeserp",free),("exa",exa)],delay=lambda _:None)
        with tempfile.TemporaryDirectory() as temp,patch("builtins.print"):
            home=Path(temp);day=dt.datetime.now(k.TORONTO).date()
            self.assertEqual(weekly(home,BASE,day,collector),0)
            self.assertEqual(len(calls),240)
            self.assertEqual(weekly(home,BASE,day,collector),0)
            self.assertEqual(len(calls),240)
            folder=home/(day-dt.timedelta(days=day.weekday())).isoformat()
            with (folder/"weekly-index-visibility.csv").open() as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),60)
            self.assertTrue(all(r["unique_index_leads_with_postal_text"]=="1" and r["union_index_leads"]=="2" and r["active_pt_competitors"]=="" for r in rows))
            self.assertTrue(all(r["directory_url"].endswith(r["fsa"].lower()) for r in rows))
            d=json.loads((folder/(day.isoformat()+".json")).read_text())
            with BASE.open() as f:baseline=list(csv.DictReader(f))
            d["observations"][0]["postal_text_ids"]=["99999"]
            self.assertFalse(audit(d,baseline)["index_survey_verified"])
    def test_partial_source_is_not_zero(self):
        def blocked(q):raise k.Unavailable("HTTP 429")
        def free(q):return {"results":[]}
        def collector(**kwargs):
            return k.survey(**kwargs,sources=[("freeserp",free),("exa",blocked)],delay=lambda _:None)
        with tempfile.TemporaryDirectory() as temp,patch("builtins.print"):
            home=Path(temp);day=dt.datetime.now(k.TORONTO).date()
            self.assertEqual(weekly(home,BASE,day,collector),3)
            folder=home/(day-dt.timedelta(days=day.weekday())).isoformat()
            with (folder/"weekly-index-visibility.csv").open() as f:rows=list(csv.DictReader(f))
            self.assertTrue(all(r["union_index_leads"]=="" and r["status"]=="unavailable" for r in rows))
if __name__=="__main__":unittest.main()
