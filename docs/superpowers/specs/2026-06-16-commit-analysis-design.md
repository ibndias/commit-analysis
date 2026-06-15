# Commit Analysis Script — Design

**Date:** 2026-06-16
**Status:** Approved

## Goal

A script that pulls your recent GitHub work and analyzes, for commits in the past 7 days:
- **Code quality** — scored per commit by an LLM against a rubric.
- **Estimated hours** — derived from commit-timestamp session clustering, adjusted by LLM complexity.

Accuracy of the analysis is the priority; the LLM prompt is carefully tuned for calibrated, structured output.

## Stack

- **Language:** Python 3, standard library only (`urllib`, `subprocess`, `json`, `argparse`, `os`, `tempfile`, `datetime`, `re`). No pip dependencies.
- **LLM:** OpenRouter, model `google/gemma-4-26b-a4b-it` (override via `--model` / `OPENROUTER_MODEL`).
- **GitHub:** `gh` CLI for repo discovery and auth; `git` for cloning and history.
- **Secrets:** loaded from `.env` (stdlib parser) or process env; env overrides file. `.env` is gitignored.

## Layout

```
commit-analysis/
  analyze.py          # entrypoint + orchestration
  .env                # OPENROUTER_API_KEY, OPENROUTER_MODEL (gitignored)
  .gitignore
  tests/
    test_sessions.py  # session clustering
    test_identity.py  # author identity matching
  docs/superpowers/specs/...
```

Single-file `analyze.py` is acceptable given size; pure-logic functions (clustering, identity, parsing) are split into module-level functions so they're unit-testable without network or git.

## Components

Each unit has one purpose, a clear interface, and is testable in isolation.

### 1. Config / secrets
- `load_env(path)` — parse `.env` into a dict (ignore comments/blanks, `KEY=VALUE`). Process env wins over file.
- Resolve `OPENROUTER_API_KEY` (required → fail-fast with clear message if absent) and `OPENROUTER_MODEL` (default the Gemma slug).
- CLI flags: `--repo <path|url>`, `--all` (default when no `--repo`), `--since "1 week ago"`, `--gap-minutes 90`, `--max-diff-chars 12000`, `--model`, `--out-dir .`.

### 2. Repo resolve  →  `list[RepoRef]`
- If `--repo`: a local path is used directly; a URL/`owner/name` is shallow-cloned (`git clone --filter=blob:none`) into a temp dir.
- Else `--all`: `gh api` for the authenticated user's repos with `pushed_at` within the window; shallow-clone each to temp dirs.
- Temp clones cleaned up at the end.

### 3. Identity resolve  →  `set[str]`
- Gather your author identities: `git config user.email`, `git config user.name`, and `gh api user` → `login`, numeric `id`, and the `id+login@users.noreply.github.com` form.
- Used to filter `git log` to *your* commits only.

### 4. Commit collect  →  `list[Commit]`
- Per repo: `git log --since=<since> --author=<each identity>` (union), `--no-merges`.
- Per commit capture: sha, ISO author timestamp, subject/body, numstat (files, insertions, deletions), and full diff via `git show` (truncated to `--max-diff-chars` with a marker).

### 5. Hours estimate  →  per-session + total
- Sort commits by time; split into sessions where the inter-commit gap exceeds `--gap-minutes`.
- Session active time = `last_commit - first_commit`.
- **Lead-in:** each session's first commit had pre-commit work not visible in timestamps. Lead-in minutes = a function of the first commit's LLM `complexity` (1–5) and diff size, bounded to `[5, 90]` min.
- Total hours = Σ(session active time + session lead-in).
- Pure heuristic except the single complexity input from the LLM; deterministic given fixed inputs.

### 6. Quality + complexity (LLM)  →  per-commit scores
- Per commit, POST to OpenRouter chat completions with the tuned prompt + truncated diff.
- **Tuned prompt:**
  - System role: senior code reviewer; output JSON ONLY, no prose.
  - Rubric for `quality_score` (1–10): correctness, readability, structure/design, test presence, commit-message hygiene — with explicit anchor descriptions for scores 2/5/8 so output is calibrated, not clustered at 7–8.
  - `complexity` (1–5) with anchors; `est_lead_in_min` realistic; `rationale` ≤ 2 sentences.
  - `temperature: 0.2`, `response_format` JSON if supported, plus defensive JSON extraction from the reply.
  - Few-shot: one trivial-diff anchor and one complex-diff anchor.
- Strict parse; on bad/again-bad output, retry with backoff, then mark commit scores `null` and continue.

### 7. Aggregate + output
- **`report-YYYY-MM-DD.md`:** header (window, scope), per-repo section, totals (commits, est hours, avg quality), and a per-commit table (sha, subject, files, +/−, quality, complexity, hours-attributed).
- **`report-YYYY-MM-DD.json`:** full structured data (every commit, every score, session breakdown) for downstream use.

## Error handling

| Case | Behavior |
|------|----------|
| Missing `OPENROUTER_API_KEY` | Exit non-zero, clear message. |
| `gh`/`git` missing or unauth | Exit with actionable message. |
| OpenRouter API error / rate limit | Retry with exponential backoff (e.g. 3 tries); then null scores, continue. |
| Diff larger than `--max-diff-chars` | Truncate, append `...[truncated]`, note in JSON. |
| No commits in window | Write empty-but-valid report, exit 0. |
| Temp clone failure | Skip that repo, warn, continue others. |

## Testing

- `tests/test_sessions.py` — clustering: single session, multi-session by gap, empty, single commit, boundary at exactly gap threshold.
- `tests/test_identity.py` — identity matching: email match, noreply form, case-insensitivity, non-match excluded.
- LLM and network are not hit in tests (pure functions only). Manual smoke run against one real repo for end-to-end validation.

## Out of scope (YAGNI)

- No web UI, no DB, no historical trend tracking across runs.
- No multi-author team analytics — *your* commits only.
- No language-specific static linters in v1 (LLM covers quality); can add later.
