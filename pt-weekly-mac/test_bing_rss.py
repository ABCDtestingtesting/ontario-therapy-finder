import unittest
from bing_rss_probe import *
class RSS(unittest.TestCase):
    def test_feed(self):
        rows=parse_rss(b'<rss><channel><item><link>https://www.psychologytoday.com/ca/therapists/m3n</link><title>Therapists</title><description>Number of Counsellors in M3N &lt;10</description></item></channel></rss>')
        self.assertEqual(extract("freeserp",rows,"M3N"),[("<10",None)])
    def test_reject_html(self):
        with self.assertRaises(Unavailable):parse_rss(b'<html><body>blocked</body></html>')
    def test_reject_dtd(self):
        with self.assertRaises(Unavailable):parse_rss(b'<!DOCTYPE rss><rss/>')
if __name__=="__main__":unittest.main()
