import sys
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auto_news as news


class AjaxNewsTests(unittest.TestCase):
    def item(self, title, category="Transfers", hours=2):
        return {
            "title": title,
            "category": category,
            "published_dt": datetime.now(timezone.utc),
            "source_weight": 3.0,
            "hours_old": hours,
            "official": False,
        }

    def test_blocks_gambling(self):
        self.assertTrue(news.is_blocked("Wedden op Ajax: 5x je inzet", ""))
        self.assertTrue(news.is_blocked("Ajax favoriet", "Bekijk de odds bij de bookmaker"))

    def test_relevance(self):
        self.assertTrue(news.is_ajax_relevant("Ajax rondt transfer af", "", False))
        self.assertFalse(news.is_ajax_relevant("PSV rondt transfer af", "", False))

    def test_categories(self):
        self.assertEqual(news.category_hint("Ajax bereikt transferakkoord", ""), "Transfers")
        self.assertEqual(news.category_hint("Ajacied mist duel door blessure", ""), "Blessures")

    def test_transfer_event_clusters_on_name(self):
        a = self.item("Ajax bereikt akkoord over Viktor Tsygankov")
        b = self.item("Tsygankov op weg naar Amsterdam na deal met Ajax")
        docs = [a, b]
        df = Counter()
        for item in docs:
            df.update(news.subject_tokens(item["title"]))
        self.assertTrue(news.same_event(a, b, df, len(docs)))

    def test_different_transfers_do_not_cluster(self):
        a = self.item("Ajax bereikt akkoord over Viktor Tsygankov")
        b = self.item("Ajax toont interesse in nieuwe verdediger Torrents")
        docs = [a, b]
        df = Counter()
        for item in docs:
            df.update(news.subject_tokens(item["title"]))
        self.assertFalse(news.same_event(a, b, df, len(docs)))


if __name__ == "__main__":
    unittest.main()
