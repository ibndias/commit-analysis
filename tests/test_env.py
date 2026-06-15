import os, tempfile, unittest
from analyze import load_env

class TestLoadEnv(unittest.TestCase):
    def test_parses_keys_and_ignores_comments(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# comment\n\nOPENROUTER_API_KEY=abc123\nOPENROUTER_MODEL=google/x\n")
            path = f.name
        env = load_env(path)
        self.assertEqual(env["OPENROUTER_API_KEY"], "abc123")
        self.assertEqual(env["OPENROUTER_MODEL"], "google/x")

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_env("/no/such/file.env"), {})

    def test_strips_quotes_and_whitespace(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write('KEY = "spaced value" \n')
            path = f.name
        self.assertEqual(load_env(path)["KEY"], "spaced value")

if __name__ == "__main__":
    unittest.main()
