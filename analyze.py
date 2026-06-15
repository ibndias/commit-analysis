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
