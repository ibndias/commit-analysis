# Commit Analysis Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stdlib-only Python script that collects your past-7-day commits (one repo or all your GitHub repos) and reports per-commit code quality and estimated hours, using OpenRouter Gemma for scoring and commit-timestamp session clustering for time.

**Architecture:** Single `analyze.py` with focused, module-level pure functions (env, identity, clustering, truncation, parsing) plus thin IO wrappers (git, gh, OpenRouter). Pure functions are unit-tested with `unittest`; network/git are exercised manually. `main()` orchestrates: resolve config → resolve repos → collect commits → LLM score → compute hours → write MD+JSON.

**Tech Stack:** Python 3 stdlib (`argparse`, `urllib`, `subprocess`, `json`, `os`, `tempfile`, `datetime`, `re`, `unittest`), `git`, `gh` CLI, OpenRouter chat completions API.

---

## File Structure

```
commit-analysis/
  analyze.py               # entrypoint + all logic (functions are individually testable)
  .env                     # secrets (gitignored, already created)
  .gitignore               # already created
  tests/
    __init__.py
    test_env.py            # load_env parser
    test_identity.py       # identity matching
    test_sessions.py       # session clustering + hours
    test_truncate.py       # diff truncation
    test_parse.py          # LLM JSON extraction
```

`analyze.py` exposes these pure functions (tested) and IO functions (manual):
- Pure: `load_env`, `match_author`, `cluster_sessions`, `lead_in_minutes`, `truncate_diff`, `extract_json`, `compute_hours`, `build_prompt`, `render_markdown`.
- IO: `resolve_repos`, `collect_commits`, `score_commit`, `main`.

---

## Task 1: Scaffold + git init

**Files:**
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Init git so commits work**

Run:
```bash
cd /home/kali/ws/commit-analysis && git init && git add .gitignore .env.example 2>/dev/null; git add -A
```
Note: `.env` is gitignored; confirm `git status` does NOT list `.env`.

- [ ] **Step 2: Create empty test package marker**

Create `tests/__init__.py` with no content.

- [ ] **Step 3: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add -A
git commit -m "chore: scaffold commit-analysis project"
```

---

## Task 2: Env loader

**Files:**
- Create: `analyze.py`
- Test: `tests/test_env.py`

- [ ] **Step 1: Write the failing test**

`tests/test_env.py`:
```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_env -v`
Expected: FAIL — `ImportError` / `cannot import name 'load_env'`.

- [ ] **Step 3: Implement**

Create `analyze.py` starting with:
```python
#!/usr/bin/env python3
"""Analyze your past-week commits: code quality + estimated hours."""
import os


def load_env(path):
    """Parse a .env file into a dict. Returns {} if file missing."""
    result = {}
    if not os.path.exists(path):
        return result
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'").strip()
            if key:
                result[key] = val
    return result
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_env -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py tests/test_env.py
git commit -m "feat: add .env loader"
```

---

## Task 3: Author identity matching

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_identity.py`

- [ ] **Step 1: Write the failing test**

`tests/test_identity.py`:
```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_identity -v`
Expected: FAIL — `cannot import name 'match_author'`.

- [ ] **Step 3: Implement** — append to `analyze.py`:
```python
def match_author(commit_email, commit_name, identities):
    """True if a commit's author email or name matches any of your identities.
    identities: set of lowercase emails/logins."""
    ident = {i.lower() for i in identities}
    if commit_email and commit_email.lower() in ident:
        return True
    if commit_name and commit_name.lower() in ident:
        return True
    return False
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_identity -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py tests/test_identity.py
git commit -m "feat: add author identity matching"
```

---

## Task 4: Session clustering + lead-in + hours

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_sessions.py`

- [ ] **Step 1: Write the failing test**

`tests/test_sessions.py`:
```python
import unittest
from datetime import datetime, timedelta
from analyze import cluster_sessions, lead_in_minutes, compute_hours

def t(mins):
    return datetime(2026, 6, 16, 9, 0) + timedelta(minutes=mins)

class TestSessions(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cluster_sessions([], 90), [])

    def test_single_commit(self):
        s = cluster_sessions([t(0)], 90)
        self.assertEqual(len(s), 1)
        self.assertEqual(len(s[0]), 1)

    def test_splits_on_large_gap(self):
        times = [t(0), t(30), t(200), t(210)]  # gap 170 > 90 splits
        s = cluster_sessions(times, 90)
        self.assertEqual([len(x) for x in s], [2, 2])

    def test_boundary_equal_gap_same_session(self):
        s = cluster_sessions([t(0), t(90)], 90)  # exactly 90 -> not > 90
        self.assertEqual(len(s), 1)

class TestLeadIn(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(lead_in_minutes(1, 0), 5)       # min clamp
        self.assertEqual(lead_in_minutes(5, 100000), 90) # max clamp
        self.assertTrue(5 <= lead_in_minutes(3, 500) <= 90)

class TestComputeHours(unittest.TestCase):
    def test_active_plus_leadin(self):
        # one session 60 min active, complexity 1 -> lead-in 5 min => 65 min
        sessions = [[t(0), t(60)]]
        complexities = {0: 1}
        diffsizes = {0: 0}
        hrs = compute_hours(sessions, complexities, diffsizes)
        self.assertAlmostEqual(hrs, (60 + 5) / 60.0, places=3)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_sessions -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement** — append to `analyze.py`:
```python
def cluster_sessions(times, gap_minutes):
    """Group sorted datetimes into sessions; new session when gap > gap_minutes."""
    if not times:
        return []
    times = sorted(times)
    sessions = [[times[0]]]
    for prev, cur in zip(times, times[1:]):
        if (cur - prev).total_seconds() / 60.0 > gap_minutes:
            sessions.append([cur])
        else:
            sessions[-1].append(cur)
    return sessions


def lead_in_minutes(complexity, diff_size):
    """Estimate pre-first-commit work, bounded [5, 90] min.
    complexity 1-5 from LLM; diff_size = insertions+deletions."""
    base = 5 + (complexity - 1) * 10  # 5..45 for complexity 1-5
    size_bonus = min(diff_size / 20.0, 50)  # up to +50
    return int(max(5, min(90, base + size_bonus)))


def compute_hours(sessions, complexities, diff_sizes):
    """Total hours = sum of (session active minutes + first-commit lead-in).
    complexities/diff_sizes keyed by commit index across the flat ordering."""
    total_min = 0.0
    idx = 0
    for sess in sessions:
        active = (sess[-1] - sess[0]).total_seconds() / 60.0
        first_idx = idx
        total_min += active + lead_in_minutes(
            complexities.get(first_idx, 3), diff_sizes.get(first_idx, 0)
        )
        idx += len(sess)
    return total_min / 60.0
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_sessions -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py tests/test_sessions.py
git commit -m "feat: add session clustering and hours estimate"
```

---

## Task 5: Diff truncation

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_truncate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_truncate.py`:
```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_truncate -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement** — append to `analyze.py`:
```python
def truncate_diff(text, max_chars):
    """Return (text, was_truncated). Appends marker if cut."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "...[truncated]", True
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_truncate -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py tests/test_truncate.py
git commit -m "feat: add diff truncation"
```

---

## Task 6: LLM JSON extraction + prompt builder

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_parse.py`

- [ ] **Step 1: Write the failing test**

`tests/test_parse.py`:
```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_parse -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement** — append to `analyze.py` (add `import json, re` at top with existing imports):
```python
import json
import re


def extract_json(text):
    """Pull the first JSON object out of an LLM reply. None if not found."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = brace.group(0) if brace else None
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


PROMPT_SYSTEM = (
    "You are a meticulous senior code reviewer. "
    "Output ONLY a single JSON object, no prose, no code fences.\n"
    "Schema: {\"quality_score\": int 1-10, \"complexity\": int 1-5, "
    "\"est_lead_in_min\": int, \"rationale\": string <= 2 sentences}.\n\n"
    "quality_score rubric (be calibrated, do NOT cluster at 7-8):\n"
    "  2 = buggy or incoherent, no structure, no tests.\n"
    "  5 = works but mediocre: weak naming/structure, no tests, terse message.\n"
    "  8 = correct, readable, well-structured, sensible message; tests if warranted.\n"
    "  10 = exemplary: clear design, thorough tests, excellent message.\n"
    "Judge: correctness, readability, structure/design, test presence, commit-message hygiene.\n"
    "complexity rubric: 1=trivial/format, 3=moderate feature, 5=intricate cross-cutting logic.\n"
    "est_lead_in_min: realistic minutes of thinking/work before this commit."
)

FEWSHOT = [
    {"role": "user", "content": "Commit subject: fix typo in README\n\nDiff:\n- teh\n+ the"},
    {"role": "assistant", "content": '{"quality_score": 6, "complexity": 1, "est_lead_in_min": 5, "rationale": "Trivial correct fix, clear subject, nothing to test."}'},
    {"role": "user", "content": "Commit subject: add retry with backoff to API client\n\nDiff:\n+def call(...):\n+  for i in range(3): ... exponential sleep ...\n+ tests for retry"},
    {"role": "assistant", "content": '{"quality_score": 8, "complexity": 3, "est_lead_in_min": 35, "rationale": "Solid resilient design with tests and a descriptive message."}'},
]


def build_prompt(subject, diff_text):
    """Return OpenRouter chat messages for scoring one commit."""
    msgs = [{"role": "system", "content": PROMPT_SYSTEM}]
    msgs.extend(FEWSHOT)
    msgs.append({
        "role": "user",
        "content": "Commit subject: {}\n\nDiff:\n{}".format(subject, diff_text),
    })
    return msgs
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_parse -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py tests/test_parse.py
git commit -m "feat: add tuned scoring prompt and JSON extraction"
```

---

## Task 7: OpenRouter client

**Files:**
- Modify: `analyze.py`

- [ ] **Step 1: Implement the API call (manual-tested IO)** — append to `analyze.py` (add `import urllib.request, urllib.error, time` to imports):
```python
import urllib.request
import urllib.error
import time

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def call_openrouter(messages, api_key, model, retries=3):
    """POST chat messages; return assistant text. Raises after retries."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(OPENROUTER_URL, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError("OpenRouter failed after {} tries: {}".format(retries, last_err))


def score_commit(subject, diff_text, api_key, model):
    """Return parsed score dict or a null-filled dict on failure."""
    try:
        reply = call_openrouter(build_prompt(subject, diff_text), api_key, model)
        parsed = extract_json(reply)
        if parsed is None:
            raise ValueError("unparseable reply")
        return {
            "quality_score": parsed.get("quality_score"),
            "complexity": parsed.get("complexity"),
            "est_lead_in_min": parsed.get("est_lead_in_min"),
            "rationale": parsed.get("rationale", ""),
        }
    except Exception as e:
        return {"quality_score": None, "complexity": None,
                "est_lead_in_min": None, "rationale": "scoring failed: {}".format(e)}
```

- [ ] **Step 2: Smoke-test the client against the real API**

Run (uses your `.env`):
```bash
cd /home/kali/ws/commit-analysis && python3 -c "
from analyze import load_env, score_commit
e = load_env('.env')
print(score_commit('add retry logic', 'def f():\n+  for i in range(3): pass', e['OPENROUTER_API_KEY'], e.get('OPENROUTER_MODEL','google/gemma-4-26b-a4b-it')))
"
```
Expected: a dict with integer `quality_score` and `complexity` (not null). If null, inspect the printed rationale.

- [ ] **Step 3: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py
git commit -m "feat: add OpenRouter client and commit scoring"
```

---

## Task 8: Repo resolve + commit collection

**Files:**
- Modify: `analyze.py`

- [ ] **Step 1: Implement git/gh IO** — append to `analyze.py` (add `import subprocess, tempfile, datetime as dt` to imports):
```python
import subprocess
import tempfile
import datetime as dt

GIT_SEP = "\x1f"   # unit separator between fields
GIT_REC = "\x1e"   # record separator between commits


def _run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


def resolve_identities(repo_path):
    """Collect your author identities from git config + gh."""
    ids = set()
    for key in ("user.email", "user.name"):
        try:
            v = _run(["git", "config", key], cwd=repo_path).strip()
            if v:
                ids.add(v)
        except subprocess.CalledProcessError:
            pass
    try:
        user = json.loads(_run(["gh", "api", "user"]))
        login, uid = user.get("login"), user.get("id")
        if login:
            ids.add(login)
        if login and uid:
            ids.add("{}+{}@users.noreply.github.com".format(uid, login))
    except Exception:
        pass
    return ids


def resolve_repos(repo_arg, since_days):
    """Return list of (name, local_path, temp_or_None)."""
    repos = []
    if repo_arg:
        if os.path.isdir(repo_arg):
            repos.append((os.path.basename(os.path.abspath(repo_arg)), repo_arg, None))
        else:
            repos.append(_clone(repo_arg))
        return repos
    # --all: discover pushed repos via gh
    raw = _run(["gh", "api", "--paginate",
                "/user/repos?affiliation=owner&sort=pushed&per_page=100"])
    for r in json.loads(raw):
        pushed = r.get("pushed_at", "")
        if not pushed:
            continue
        when = dt.datetime.strptime(pushed, "%Y-%m-%dT%H:%M:%SZ")
        if (dt.datetime.utcnow() - when).days <= since_days:
            try:
                repos.append(_clone(r["clone_url"]))
            except Exception as e:
                print("WARN: skip {}: {}".format(r.get("full_name"), e))
    return repos


def _clone(url):
    tmp = tempfile.mkdtemp(prefix="ca_")
    _run(["git", "clone", "--filter=blob:none", "--quiet", url, tmp])
    name = url.rstrip("/").split("/")[-1].replace(".git", "")
    return (name, tmp, tmp)


def collect_commits(repo_path, identities, since, max_diff_chars):
    """Return list of commit dicts authored by you within the window, time-sorted."""
    fmt = GIT_SEP.join(["%H", "%aI", "%ae", "%an", "%s"]) + GIT_REC
    log = _run(["git", "log", "--no-merges", "--since=" + since,
                "--pretty=format:" + fmt], cwd=repo_path)
    commits = []
    for rec in log.split(GIT_REC):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, aiso, email, name, subject = rec.split(GIT_SEP)
        if not match_author(email, name, identities):
            continue
        numstat = _run(["git", "show", "--numstat", "--format=", sha], cwd=repo_path)
        ins = dele = 0
        for ln in numstat.splitlines():
            parts = ln.split("\t")
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                ins += int(parts[0]); dele += int(parts[1])
        diff = _run(["git", "show", "--format=", sha], cwd=repo_path)
        diff, was_trunc = truncate_diff(diff, max_diff_chars)
        commits.append({
            "sha": sha[:10], "time": dt.datetime.fromisoformat(aiso).replace(tzinfo=None),
            "subject": subject, "insertions": ins, "deletions": dele,
            "diff": diff, "truncated": was_trunc,
        })
    commits.sort(key=lambda c: c["time"])
    return commits
```

- [ ] **Step 2: Smoke-test collection on this repo**

Run:
```bash
cd /home/kali/ws/commit-analysis && python3 -c "
from analyze import resolve_identities, collect_commits
ids = resolve_identities('.')
print('identities:', ids)
cs = collect_commits('.', ids, '1 week ago', 12000)
print('commits found:', len(cs))
for c in cs[:3]: print(c['sha'], c['subject'], c['insertions'], c['deletions'])
"
```
Expected: prints your identities and the commits made so far in this project.

- [ ] **Step 3: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py
git commit -m "feat: add repo resolution and commit collection"
```

---

## Task 9: Markdown rendering

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_parse.py` (add render test here to keep one render test file) — use new `tests/test_render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

`tests/test_render.py`:
```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_render -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement** — append to `analyze.py`:
```python
def render_markdown(data):
    """Render the report dict to a Markdown string."""
    out = []
    out.append("# Commit Analysis — {}".format(data["generated"]))
    out.append("")
    out.append("Window: commits since **{}**".format(data["window"]))
    out.append("")
    out.append("**Totals:** {} commits · {:.1f} estimated hours".format(
        data["total_commits"], data["total_hours"]))
    out.append("")
    for repo in data["repos"]:
        out.append("## {}".format(repo["name"]))
        out.append("")
        out.append("- Estimated hours: **{:.1f}**".format(repo["hours"]))
        aq = repo["avg_quality"]
        out.append("- Average quality: **{}**".format(
            "{:.1f}".format(aq) if aq is not None else "n/a"))
        out.append("")
        out.append("| sha | subject | +/- | quality | complexity |")
        out.append("|-----|---------|-----|---------|------------|")
        for c in repo["commits"]:
            out.append("| {} | {} | +{}/-{} | {} | {} |".format(
                c["sha"], c["subject"].replace("|", "\\|"),
                c["insertions"], c["deletions"],
                c.get("quality_score", "n/a"), c.get("complexity", "n/a")))
        out.append("")
    return "\n".join(out)
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest tests.test_render -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py tests/test_render.py
git commit -m "feat: add markdown report rendering"
```

---

## Task 10: CLI orchestration (main)

**Files:**
- Modify: `analyze.py`

- [ ] **Step 1: Implement `main` + arg parsing** — append to `analyze.py` (add `import argparse` to imports):
```python
import argparse


def analyze_repo(name, path, identities, args, api_key, model):
    """Collect, score, and compute hours for one repo. Returns repo result dict."""
    commits = collect_commits(path, identities, args.since, args.max_diff_chars)
    complexities, diff_sizes = {}, {}
    for i, c in enumerate(commits):
        score = score_commit(c["subject"], c["diff"], api_key, model)
        c.update(score)
        complexities[i] = score["complexity"] or 3
        diff_sizes[i] = c["insertions"] + c["deletions"]
    sessions = cluster_sessions([c["time"] for c in commits], args.gap_minutes)
    hours = compute_hours(sessions, complexities, diff_sizes)
    quals = [c["quality_score"] for c in commits if c["quality_score"] is not None]
    avg_q = sum(quals) / len(quals) if quals else None
    for c in commits:
        c["time"] = c["time"].isoformat()
        c.pop("diff", None)
    return {"name": name, "hours": hours, "avg_quality": avg_q, "commits": commits}


def main(argv=None):
    p = argparse.ArgumentParser(description="Analyze your past-week commits.")
    p.add_argument("--repo", help="path or URL of a single repo")
    p.add_argument("--all", action="store_true", help="analyze all your repos (default)")
    p.add_argument("--since", default="1 week ago")
    p.add_argument("--since-days", type=int, default=7, help="window for --all repo discovery")
    p.add_argument("--gap-minutes", type=int, default=90)
    p.add_argument("--max-diff-chars", type=int, default=12000)
    p.add_argument("--model", default=None)
    p.add_argument("--out-dir", default=".")
    p.add_argument("--env", default=".env")
    args = p.parse_args(argv)

    env = load_env(args.env)
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY")
    if not api_key:
        p.error("OPENROUTER_API_KEY not set (env or .env)")
    model = (args.model or os.environ.get("OPENROUTER_MODEL")
             or env.get("OPENROUTER_MODEL") or "google/gemma-4-26b-a4b-it")

    repos = resolve_repos(args.repo, args.since_days)
    if not repos:
        print("No repositories to analyze.")
        return

    results = []
    for name, path, _tmp in repos:
        identities = resolve_identities(path)
        results.append(analyze_repo(name, path, identities, args, api_key, model))

    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    data = {
        "generated": today, "window": args.since,
        "repos": results,
        "total_hours": sum(r["hours"] for r in results),
        "total_commits": sum(len(r["commits"]) for r in results),
    }
    json_path = os.path.join(args.out_dir, "report-{}.json".format(today))
    md_path = os.path.join(args.out_dir, "report-{}.md".format(today))
    with open(json_path, "w") as fh:
        json.dump(data, fh, indent=2)
    with open(md_path, "w") as fh:
        fh.write(render_markdown(data))
    print("Wrote {} and {}".format(md_path, json_path))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full unit suite**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 3: End-to-end smoke run on this repo**

Run:
```bash
cd /home/kali/ws/commit-analysis && python3 analyze.py --repo . --out-dir /tmp
```
Expected: `Wrote /tmp/report-2026-06-16.md and /tmp/report-2026-06-16.json`; open the MD and confirm a per-commit table with quality + a non-zero hours total.

- [ ] **Step 4: Commit**

```bash
cd /home/kali/ws/commit-analysis
git add analyze.py
git commit -m "feat: add CLI orchestration and report output"
```

---

## Task 11: README + final verification

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

`README.md`:
```markdown
# commit-analysis

Analyze your past-week commits for code quality and estimated hours.

## Setup
1. `gh auth login` (GitHub CLI authenticated)
2. Put your OpenRouter key in `.env`: `OPENROUTER_API_KEY=sk-or-...`

## Usage
    python3 analyze.py                 # all your repos pushed in the last 7 days
    python3 analyze.py --repo .        # a single local repo
    python3 analyze.py --repo owner/x  # a single remote repo (cloned)

Flags: `--since`, `--gap-minutes`, `--max-diff-chars`, `--model`, `--out-dir`.

Outputs `report-YYYY-MM-DD.md` and `.json`.

## How hours are estimated
Commits are grouped into work sessions (gap > 90 min starts a new session).
Each session contributes its active span plus a lead-in for the first commit,
sized by the LLM's complexity rating. Approximate by nature.
```

- [ ] **Step 2: Full suite + commit**

Run: `cd /home/kali/ws/commit-analysis && python3 -m unittest discover -s tests`
Expected: OK.

```bash
cd /home/kali/ws/commit-analysis
git add README.md
git commit -m "docs: add README"
```

---

## Self-Review Notes

- **Spec coverage:** env loading (T2), identity (T3), sessions+hours (T4), truncation (T5), prompt+parse (T6), OpenRouter client (T7), repo resolve + collect (T8), MD render (T9), JSON+CLI+orchestration (T10), docs (T11). All spec sections mapped.
- **Type consistency:** commit dict keys (`sha`, `time`, `subject`, `insertions`, `deletions`, `diff`, `truncated`, `quality_score`, `complexity`, `est_lead_in_min`, `rationale`) consistent across collect/score/render. `compute_hours` index keying matches flat time-sorted order used in `analyze_repo`.
- **Placeholders:** none — every code step is complete.
- **Known approximation:** `resolve_repos --all` uses `utcnow()` vs `pushed_at`; acceptable for a 7-day window.
