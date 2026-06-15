import unittest
from analyze import truncate_diff

class TestTruncate(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(truncate_diff("abc", 100), ("abc", False))

    def test_long_truncated_with_marker(self):
        text = "x" * 200
        out, was = truncate_diff(text, 50)
        self.assertTrue(was)
        self.assertTrue(out.endswith("...[truncated]"))
        self.assertLessEqual(len(out), 50 + len("...[truncated]"))
