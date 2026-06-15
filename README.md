# commit-analysis

Analyze your past-week git commits for **code quality** and **estimated hours**.
Commits are scored by an LLM (OpenRouter) against a calibrated rubric; hours are
estimated from commit-timestamp work sessions. Outputs a Markdown report and JSON.

Pure Python 3 standard library — no `pip install` needed.

## Requirements
- Python 3.8+
- [`git`](https://git-scm.com/) and [`gh`](https://cli.github.com/) on `PATH`
- An [OpenRouter](https://openrouter.ai/) API key

## Setup
1. Authenticate the GitHub CLI (used to discover your repos and identity):
   ```bash
   gh auth login
   ```
2. Put your OpenRouter key in a `.env` file next to `analyze.py`:
   ```
   OPENROUTER_API_KEY=sk-or-...
   OPENROUTER_MODEL=google/gemma-4-26b-a4b-it
   ```
   (`.env` is gitignored. The key can also come from the environment instead of `.env`.)

## How to run
```bash
cd ~/ws/commit-analysis

# Analyze a single local repo (the current directory)
python3 analyze.py --repo .

# Analyze a single remote repo (shallow-cloned to a temp dir, then cleaned up)
python3 analyze.py --repo owner/name

# Analyze ALL repos you pushed to in the last 7 days (default when no --repo)
python3 analyze.py

# Write reports somewhere other than the current dir
python3 analyze.py --repo . --out-dir /tmp
```

Only commits authored by **you** are counted (matched against your `git config`
email/name and your GitHub login + noreply email).

### Flags
| Flag | Default | Meaning |
|------|---------|---------|
| `--repo PATH\|URL` | _(none → `--all`)_ | One repo: local path, or remote `owner/name`/URL |
| `--since` | `"1 week ago"` | Commit window (any `git log --since` expression) |
| `--since-days` | `7` | Window for `--all` repo discovery (days since last push) |
| `--gap-minutes` | `90` | Idle gap that starts a new work session |
| `--max-diff-chars` | `12000` | Diff truncation limit sent to the LLM |
| `--model` | `google/gemma-4-26b-a4b-it` | OpenRouter model slug |
| `--out-dir` | `.` | Where to write the reports |
| `--env` | `.env` | Path to the env file |

## Output
Two files, dated by UTC day:
- `report-YYYY-MM-DD.md` — human-readable summary + per-commit table
- `report-YYYY-MM-DD.json` — full structured data (every commit, every score)

### Example
Running `python3 analyze.py --repo . --out-dir /tmp` on this project produced:

```markdown
# Commit Analysis — 2026-06-15

Window: commits since **1 week ago**

**Totals:** 15 commits · 1.2 estimated hours

## commit-analysis

- Estimated hours: **1.2**
- Average quality: **8.5**

| sha | subject | +/- | quality | complexity |
|-----|---------|-----|---------|------------|
| a9fc13a99a | chore: scaffold commit-analysis project | +1026/-0 | 9 | 1 |
| 4883553c7b | feat: add .env loader | +44/-0 | 9 | 2 |
| d7fee5ae9b | feat: add session clustering and hours estimate | +76/-0 | 9 | 3 |
| e1c3a979e7 | feat: add repo resolution and commit collection | +95/-0 | 7 | 4 |
| ... | | | | |
```

Each commit in the JSON carries its full score:
```json
{
  "sha": "d7fee5ae9b",
  "time": "2026-06-16T05:57:40",
  "subject": "feat: add session clustering and hours estimate",
  "insertions": 76,
  "deletions": 0,
  "truncated": false,
  "quality_score": 9,
  "complexity": 3,
  "est_lead_in_min": 45,
  "rationale": "Excellent implementation with comprehensive unit tests covering edge cases and boundary conditions. The logic is clean, well-documented, and follows a clear mathematical model."
}
```

## How quality is scored
Each commit's subject + diff is sent to the model with a tuned prompt: an explicit
1–10 rubric with anchor descriptions (so scores don't all cluster at 7–8), a 1–5
complexity scale, and two few-shot calibration examples. Temperature is 0.2 for
stable output. Judged dimensions: correctness, readability, structure/design, test
presence, and commit-message hygiene.

## How hours are estimated
Commits are grouped into work sessions (a gap > `--gap-minutes` starts a new
session). Each session contributes its active span (last − first commit) plus a
lead-in for its first commit, sized by the LLM's complexity rating and the diff
size, bounded to 5–90 minutes. This is an approximation — git records commit
timestamps, not time actually spent.

## Tests
```bash
python3 -m unittest discover -s tests
```
Pure-logic functions (env parsing, identity matching, session clustering, hours,
truncation, JSON extraction, rendering) are unit-tested; the network/git layers
are exercised by running the tool.
