# commit-analysis

Deep analysis of your past-week git commits: **multi-axis code quality**,
**per-commit code-review findings**, a **weekly retrospective**, repo **metrics**,
and **estimated hours**. Commits are reviewed by an LLM (via OpenRouter) against a
calibrated rubric; hours come from commit-timestamp work sessions. Outputs Markdown
+ JSON.

Pure Python 3 standard library — no `pip install` needed.

## What the analysis includes
- **Multi-axis quality** — every commit scored 1–10 on five independent axes:
  correctness, readability, design, test coverage, commit hygiene (plus an overall).
- **Code-review findings** — concrete per-commit issues (bug / security / perf /
  style / test) with severity (critical → nit), file:line, and a suggested fix.
- **Weekly insights** — an LLM retrospective over the whole week: strengths,
  weaknesses, themes, a narrative paragraph, and recommendations.
- **Repo metrics** (computed, no LLM) — file hotspots, language mix, commit
  time-of-day, rework rate, and a findings severity rollup.
- **Estimated hours** — work-session clustering with complexity-scaled lead-in.

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
   OPENROUTER_MODEL=google/gemma-4-31b-it
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

# Same, but skip your PRIVATE repos (useful before sharing a report)
python3 analyze.py --public-only

# Write reports somewhere other than the current dir
python3 analyze.py --repo . --out-dir /tmp
```

Only commits authored by **you** are counted (matched against your `git config`
email/name and your GitHub login + noreply email).

### Flags
| Flag | Default | Meaning |
|------|---------|---------|
| `--repo PATH\|URL` | _(none → `--all`)_ | One repo: local path, or remote `owner/name`/URL |
| `--public-only` | off | With `--all`, skip your private repos |
| `--since` | `"1 week ago"` | Commit window (any `git log --since` expression) |
| `--since-days` | `7` | Window for `--all` repo discovery (days since last push) |
| `--gap-minutes` | `90` | Idle gap that starts a new work session |
| `--max-diff-chars` | `12000` | Diff truncation limit sent to the LLM |
| `--model` | `google/gemma-4-31b-it` | OpenRouter model slug |
| `--out-dir` | `.` | Where to write the reports |
| `--env` | `.env` | Path to the env file |

## Output
Two files, dated by UTC day:
- `report-YYYY-MM-DD.md` — readable report: weekly insights, per-repo metrics,
  a per-commit table, and a per-commit detail section with axes + findings.
- `report-YYYY-MM-DD.json` — full structured data (every commit, every axis,
  every finding, metrics, and the weekly summary).

### Example
A real report generated from this account's **public** repos lives in
[`examples/`](examples/). A trimmed excerpt:

```markdown
# Commit Analysis — 2026-06-15

Window: commits since **1 week ago**
Model: `google/gemma-4-31b-it`

**Totals:** 16 commits · 1.3 estimated hours

## Weekly Insights

The week began with high-quality, well-tested utility work, but as the project
transitioned from scaffolding to core engine development, test coverage dropped...

**Strengths**
- High commit hygiene and consistent documentation updates
- Strong initial scaffolding and modular feature implementation

**Weaknesses**
- Severe regression in test coverage as complexity increased
- Resource management issues including temp file/directory leaks

## commit-analysis

- Estimated hours: **1.3**
- Average quality: **8.5**
- Findings: 6 major · 14 minor · 2 nit
- Avg by axis: correctness 8.9, readability 8.9, design 8.1, test coverage 6.8, commit hygiene 9.8
- Rework rate (deletions/churn): **2%**
- Hotspots: `analyze.py` (407), `README.md` (147)
- Busiest hour: **05:00** (8 commits)

| sha | subject | +/- | quality | complexity |
|-----|---------|-----|---------|------------|
| a9fc13a99a | chore: scaffold commit-analysis project | +1026/-0 | 10.0 | 1 |
| ... | | | | |

### Per-commit detail

#### `bcea31e30c` feat: add OpenRouter client and commit scoring
Quality **6.2** · complexity 3 · +48/-0

Axes: correctness 6, readability 7, design 6, test coverage 2, commit hygiene 9

- **major** (test) `analyze.py` — Network client added with no tests or mocks.
  _Fix:_ Add unittest.mock-based tests for retry/backoff and error paths.
```

## How quality is scored
Each commit's subject + diff is sent to the model with a tuned prompt: a per-axis
1–10 rubric with anchor descriptions (so scores don't all cluster at 7–8), a 1–5
complexity scale, a findings schema, and two few-shot calibration examples
(including one with a planted security bug). Temperature is 0.2 for stable output.
Each axis is scored independently; the overall quality is their mean.

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
truncation, JSON extraction, numstat parsing, multi-axis aggregation, metrics,
weekly digest, rendering) are unit-tested; the network/git layers are exercised by
running the tool.
