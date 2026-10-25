import unittest

from fetch_arxiv import build_url, parse_entries

FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <id>http://arxiv.org/api/feed123</id>
  <updated>2026-10-25T00:00:00-04:00</updated>
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <published>2024-01-01T00:00:00Z</published>
    <updated>2024-02-02T00:00:00Z</updated>
    <title>  A   spaced
      title </title>
    <summary>  An abstract </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="stat.ML"/>
    <link href="http://arxiv.org/abs/2401.00001v2" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.00001v2" rel="related" title="pdf" type="application/pdf"/>
  </entry>
</feed>"""

ERROR_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>http://arxiv.org/api/err123</id>
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_1234.12345</id>
    <title>Error</title>
    <summary>incorrect id format for 1234.12345</summary>
  </entry>
</feed>"""


class ParseEntriesTest(unittest.TestCase):
    def test_row_carries_request_id_and_retrieval_time(self):
        rows = parse_entries(FEED.encode(), "2026-10-25T12:00:00+00:00")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["request_id"], "http://arxiv.org/api/feed123")
        self.assertEqual(row["retrieved_at"], "2026-10-25T12:00:00+00:00")

    def test_entry_fields_are_cleaned(self):
        row = parse_entries(FEED.encode(), "now")[0]
        self.assertEqual(row["arxiv_id"], "2401.00001v2")
        self.assertEqual(row["title"], "A spaced title")
        self.assertEqual(row["summary"], "An abstract")
        self.assertEqual(row["authors"], "Ada Lovelace; Alan Turing")
        self.assertEqual(row["primary_category"], "cs.LG")
        self.assertEqual(row["categories"], "cs.LG; stat.ML")
        self.assertEqual(row["pdf_url"], "http://arxiv.org/pdf/2401.00001v2")

    def test_error_feed_raises(self):
        with self.assertRaises(RuntimeError):
            parse_entries(ERROR_FEED.encode(), "now")

    def test_url_encodes_query_and_caps_page(self):
        url = build_url('ti:"electron thermal" AND cat:cs.LG', 0, 1000)
        self.assertIn("max_results=1000", url)
        self.assertIn("start=0", url)
        self.assertIn("search_query=ti%3A%22electron+thermal%22+AND+cat%3Acs.LG", url)


if __name__ == "__main__":
    unittest.main()
