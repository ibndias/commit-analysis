#!/usr/bin/env python3
"""Analyze your past-week commits: code quality + estimated hours."""
import json
import os
import re
import urllib.request
import urllib.error
import time
import subprocess
import tempfile
import datetime as dt


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
