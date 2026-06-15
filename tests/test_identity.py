import unittest
from analyze import match_author

class TestMatchAuthor(unittest.TestCase):
    def setUp(self):
        self.ids = {"me@example.com", "1234+octo@users.noreply.github.com", "octo"}

    def test_email_match_case_insensitive(self):
        self.assertTrue(match_author("ME@Example.com", "Someone", self.ids))

    def test_noreply_match(self):
        self.assertTrue(match_author("1234+octo@users.noreply.github.com", "x", self.ids))

    def test_name_match(self):
        self.assertTrue(match_author("other@x.com", "octo", self.ids))

    def test_non_match_excluded(self):
        self.assertFalse(match_author("stranger@x.com", "Stranger", self.ids))
