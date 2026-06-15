import unittest
from datetime import datetime
from analyze import (
    parse_numstat, overall_quality, file_hotspots, language_mix,
    time_of_day_histogram, rework_rate, build_week_digest, build_weekly_prompt,
)


class TestParseNumstat(unittest.TestCase):
    def test_totals_and_files(self):
        text = "10\t2\tsrc/a.py\n5\t0\tREADME.md\n"
        ins, dele, files = parse_numstat(text)
        self.assertEqual((ins, dele), (15, 2))
        self.assertEqual(files[0], {"path": "src/a.py", "insertions": 10, "deletions": 2})
        self.assertEqual(len(files), 2)

    def test_binary_dashes_skipped_from_lines_but_listed(self):
        text = "-\t-\timage.png\n3\t1\ta.py\n"
        ins, dele, files = parse_numstat(text)
        self.assertEqual((ins, dele), (3, 1))
        # binary file still listed with 0/0
        paths = [f["path"] for f in files]
        self.assertIn("image.png", paths)

    def test_empty(self):
        self.assertEqual(parse_numstat(""), (0, 0, []))


class TestOverallQuality(unittest.TestCase):
    def test_mean_of_axes(self):
        scores = {"correctness": 8, "readability": 6, "design": 7,
                  "test_coverage": 4, "commit_hygiene": 10}
        self.assertEqual(overall_quality(scores), 7.0)

    def test_ignores_none_and_missing(self):
        self.assertEqual(overall_quality({"correctness": 8, "readability": None}), 8.0)

    def test_empty_returns_none(self):
        self.assertIsNone(overall_quality({}))
        self.assertIsNone(overall_quality(None))


def _c(hour, files, subject="x"):
    return {"time": datetime(2026, 6, 16, hour, 0), "subject": subject,
            "insertions": sum(f["insertions"] for f in files),
            "deletions": sum(f["deletions"] for f in files), "files": files}


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.commits = [
            _c(9, [{"path": "a.py", "insertions": 10, "deletions": 0},
                   {"path": "b.js", "insertions": 5, "deletions": 1}]),
            _c(9, [{"path": "a.py", "insertions": 3, "deletions": 7}]),
            _c(14, [{"path": "c.py", "insertions": 2, "deletions": 0}]),
        ]

    def test_file_hotspots_sorted_by_churn(self):
        hot = file_hotspots(self.commits, top_n=2)
        self.assertEqual(hot[0]["path"], "a.py")
        self.assertEqual(hot[0]["changes"], 20)  # 10+3+7
        self.assertEqual(hot[0]["commits"], 2)
        self.assertEqual(len(hot), 2)

    def test_language_mix_by_extension(self):
        mix = language_mix(self.commits)
        self.assertEqual(mix[".py"], 10 + 3 + 7 + 2)
        self.assertEqual(mix[".js"], 6)

    def test_time_of_day_histogram(self):
        hist = time_of_day_histogram(self.commits)
        self.assertEqual(hist[9], 2)
        self.assertEqual(hist[14], 1)

    def test_rework_rate(self):
        # total ins=20, del=8 -> 8/28
        self.assertAlmostEqual(rework_rate(self.commits), 8 / 28.0, places=3)

    def test_rework_rate_empty(self):
        self.assertEqual(rework_rate([]), 0.0)


class TestWeekDigest(unittest.TestCase):
    def test_digest_contains_subjects_and_scores(self):
        repos = [{
            "name": "demo",
            "commits": [{"sha": "abc1234567", "subject": "feat: add thing",
                         "quality_score": 7.5, "complexity": 3,
                         "findings": [{"severity": "major", "category": "bug",
                                       "file": "a.py", "line": 4,
                                       "issue": "off-by-one", "suggestion": "use <="}]}],
        }]
        digest = build_week_digest(repos)
        self.assertIn("feat: add thing", digest)
        self.assertIn("demo", digest)
        self.assertIn("off-by-one", digest)

    def test_weekly_prompt_has_schema_and_digest(self):
        msgs = build_weekly_prompt("DIGESTTEXT")
        joined = " ".join(m["content"] for m in msgs)
        self.assertIn("DIGESTTEXT", joined)
        self.assertIn("strengths", joined)
        self.assertIn("JSON", joined)


if __name__ == "__main__":
    unittest.main()
