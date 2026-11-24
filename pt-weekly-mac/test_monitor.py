import datetime as dt,json,tempfile,unittest
from pathlib import Path
import monitor as m
def html(fsa,ids,total,links=""):
    return f'<h1>{fsa}</h1><p>Number of Counsellors in {fsa} {total}</p>'+''.join(f'<a href="/ca/therapists/test/{x}">Profile</a>' for x in ids)+links
class TestMonitor(unittest.TestCase):
    def test_baseline(self): self.assertEqual(len(m.baseline(m.ROOT/"candidates.csv")),60)
    def test_week(self): self.assertEqual(m.week(dt.date(2026,11,29)),"2026-11-23");self.assertEqual(m.week(dt.date(2026,11,30)),"2026-11-30")
    def test_ids(self):
        self.assertEqual(m.ids(["https://www.psychologytoday.com/ca/therapists/a/12345","https://psychologytoday.com/ca/therapists/b/12345?x=y","https://evil.test/ca/therapists/a/12345"]),["12345"])
    def test_pt_dedup_paging(self):
        a=html("L3S",["10001","10002"],3,'<a href="?page=2">Next</a>')
        b=html("L3S",["10002","10003"],3)
        d=m.direct("L3S",lambda u:(b if "?page=2" in u else a,u),lambda x:None)
        self.assertEqual(d["ids"],["10001","10002","10003"]);self.assertEqual(d["status"],"visible_pages_checked");self.assertFalse(d["exact_active_advertiser_count"])
    def test_rounded_not_exact(self):
        d=m.direct("L3S",lambda u:(html("L3S",["10001"],"1+"),u),lambda x:None)
        self.assertEqual(d["status"],"partial_visible_observation")
    def test_blocked(self):
        with self.assertRaises(m.HaltSource):m.parse_pt("Verify you are human","L3S",m.BASE)
    def test_no_fake_zero(self):
        with self.assertRaises(m.SourceError):m.parse_pt("<h1>L3S</h1>","L3S",m.BASE)
    def test_wrong_location(self):
        with self.assertRaises(m.SourceError):m.direct("L3S",lambda u:(html("L3S",["10001"],1),m.BASE+"/ca/therapists/m1k"),lambda x:None)
    def test_search_headers(self):
        def fetch(url,h):
            self.assertEqual(h["X-Loc-Postal-Code"],"L3S")
            return json.dumps({"web":{"results":[{"url":"https://www.psychologytoday.com/ca/therapists/a/12345"}]},"query":{"postal_code":"L3S"}}),url
        self.assertEqual(m.search("brave","L3S",1,"fake",fetch)["ids"],["12345"])
    def test_full_60_local_pipeline(self):
        rows=m.baseline(m.ROOT/"candidates.csv");calls=[]
        def fetch(url,h=None,payload=None):
            calls.append(url)
            if "brave.com" in url:return json.dumps({"web":{"results":[]}}),url
            if "tavily.com" in url:return json.dumps({"results":[]}),url
            return html(url[-3:].upper(),["10001"],1),url
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c={"brave_key":"fake","tavily_key":"fake","pt_permission_reference":"fixture"}
            t=dt.datetime(2026,11,24,12,tzinfo=m.TZ)
            out=m.run(rows,c,root,t,fetch,lambda x:None)
            self.assertEqual(len(calls),300)
            self.assertEqual(m.load(out/"coverage.json",{})["areas_with_terminal_count_agreement"],60)
            m.run(rows,c,root,t,fetch,lambda x:None);self.assertEqual(len(calls),300)
            m.run(rows,c,root,t+dt.timedelta(days=1),fetch,lambda x:None);self.assertEqual(len(calls),600)
            self.assertEqual(m.load(out/"coverage.json",{})["areas_with_two_or_more_direct_days"],60)
            self.assertFalse(m.load(out/"coverage.json",{})["exact_ranking_certified"])
    def test_source_stop_and_missing(self):
        rows=m.baseline(m.ROOT/"candidates.csv")
        with tempfile.TemporaryDirectory() as tmp:
            def fetch(*a):raise m.HaltSource("HTTP 429")
            out=m.run(rows,{"pt_permission_reference":"fixture"},Path(tmp),dt.datetime(2026,11,24,12,tzinfo=m.TZ),fetch,lambda x:None)
            data=m.load(out/"observations.json",{});self.assertEqual(len(data),1)
            self.assertEqual(m.load(out/"coverage.json",{})["areas_with_terminal_count_agreement"],0)
            self.assertIn("incomplete_or_unavailable",(out/"by-visible-count.csv").read_text())
if __name__=="__main__":unittest.main()
