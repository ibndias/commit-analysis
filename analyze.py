#!/usr/bin/env python3
"""Analyze your past-week commits: code quality + estimated hours."""
import json
import os
import re


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


def match_author(commit_email, commit_name, identities):
    """True if a commit's author email or name matches any of your identities.
    identities: set of lowercase emails/logins."""
    ident = {i.lower() for i in identities}
    if commit_email and commit_email.lower() in ident:
        return True
    if commit_name and commit_name.lower() in ident:
        return True
    return False


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


def truncate_diff(text, max_chars):
    """Return (text, was_truncated). Appends marker if cut."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "...[truncated]", True


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
