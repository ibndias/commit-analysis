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
