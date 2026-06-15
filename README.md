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
