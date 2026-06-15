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
