import unittest
from analyze import extract_json, build_prompt

class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(extract_json('{"quality_score": 7}')["quality_score"], 7)

    def test_json_in_codefence(self):
        s = 'Here:\n```json\n{"quality_score": 5, "complexity": 2}\n```\nthanks'
        out = extract_json(s)
        self.assertEqual(out["complexity"], 2)

    def test_returns_none_on_garbage(self):
        self.assertIsNone(extract_json("no json here"))

class TestBuildPrompt(unittest.TestCase):
    def test_contains_rubric_and_diff(self):
        msgs = build_prompt("SUBJECT", "DIFFTEXT")
        joined = " ".join(m["content"] for m in msgs)
        self.assertIn("quality_score", joined)
        self.assertIn("DIFFTEXT", joined)
        self.assertIn("JSON", joined)
