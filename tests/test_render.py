import unittest
from analyze import render_markdown

class TestRender(unittest.TestCase):
    def test_includes_totals_and_table(self):
        data = {
            "window": "1 week ago", "generated": "2026-06-16",
            "repos": [{
                "name": "demo", "hours": 2.5, "avg_quality": 7.0,
                "commits": [{"sha": "abc1234567", "subject": "feat: x",
                             "insertions": 10, "deletions": 2,
                             "quality_score": 7, "complexity": 2}],
            }],
            "total_hours": 2.5, "total_commits": 1,
        }
        md = render_markdown(data)
        self.assertIn("demo", md)
        self.assertIn("2.5", md)
        self.assertIn("feat: x", md)
        self.assertIn("| sha |", md.replace("  ", " "))
