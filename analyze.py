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
import shutil
import datetime as dt
import argparse
from collections import Counter, defaultdict


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


def parse_numstat(text):
    """Parse `git show --numstat` output.
    Returns (insertions, deletions, files) where files is a list of
    {path, insertions, deletions}. Binary files (numstat '-') are listed with 0/0."""
    ins = dele = 0
    files = []
    for ln in text.splitlines():
        parts = ln.split("\t")
        if len(parts) != 3:
            continue
        a, b, path = parts
        fi = int(a) if a.isdigit() else 0
        fd = int(b) if b.isdigit() else 0
        ins += fi
        dele += fd
        files.append({"path": path, "insertions": fi, "deletions": fd})
    return ins, dele, files


QUALITY_AXES = ("correctness", "readability", "design", "test_coverage", "commit_hygiene")


def overall_quality(scores):
    """Mean of the present multi-axis scores, rounded to 1 dp. None if no values."""
    if not scores:
        return None
    vals = [v for v in scores.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def file_hotspots(commits, top_n=10):
    """Most-churned files: list of {path, changes, commits} sorted by churn desc."""
    churn = defaultdict(int)
    touched = defaultdict(int)
    for c in commits:
        for f in c.get("files", []):
            churn[f["path"]] += f["insertions"] + f["deletions"]
            touched[f["path"]] += 1
    rows = [{"path": p, "changes": churn[p], "commits": touched[p]} for p in churn]
    rows.sort(key=lambda r: (-r["changes"], r["path"]))
    return rows[:top_n]


def language_mix(commits):
    """Lines changed per file extension (lowercased). Extensionless -> '(none)'."""
    mix = Counter()
    for c in commits:
        for f in c.get("files", []):
            _root, ext = os.path.splitext(f["path"])
            ext = ext.lower() or "(none)"
            mix[ext] += f["insertions"] + f["deletions"]
    return dict(mix)


def time_of_day_histogram(commits):
    """Commit count per hour-of-day (0-23). datetime `time` field required."""
    hist = Counter()
    for c in commits:
        t = c.get("time")
        if hasattr(t, "hour"):
            hist[t.hour] += 1
    return dict(hist)


def rework_rate(commits):
    """Proxy for churn-then-rework: deletions / (insertions+deletions). 0 if none."""
    ins = sum(c.get("insertions", 0) for c in commits)
    dele = sum(c.get("deletions", 0) for c in commits)
    total = ins + dele
    return (dele / total) if total else 0.0


PROMPT_SYSTEM = (
    "You are a meticulous senior code reviewer performing a deep review of one git commit. "
    "Output ONLY a single JSON object, no prose, no code fences.\n\n"
    "Schema:\n"
    "{\n"
    '  "scores": {"correctness": int 1-10, "readability": int 1-10, "design": int 1-10, '
    '"test_coverage": int 1-10, "commit_hygiene": int 1-10},\n'
    '  "complexity": int 1-5,\n'
    '  "est_lead_in_min": int,\n'
    '  "rationale": string <= 2 sentences,\n'
    '  "findings": [ {"severity": "critical|major|minor|nit", '
    '"category": "bug|security|perf|style|test", "file": string, "line": int or null, '
    '"issue": string, "suggestion": string} ]\n'
    "}\n\n"
    "Score each axis INDEPENDENTLY and be calibrated — do NOT cluster everything at 7-8. "
    "Anchors per axis: 2 = seriously deficient, 5 = mediocre/acceptable, 8 = good, 10 = exemplary.\n"
    "  correctness: does the code do the right thing, handle edge cases, avoid bugs?\n"
    "  readability: naming, clarity, comments where needed.\n"
    "  design: structure, separation of concerns, reuse, no needless complexity.\n"
    "  test_coverage: are changes covered by tests proportionate to risk? (10 only if well-tested)\n"
    "  commit_hygiene: focused scope, clear and descriptive message.\n"
    "complexity rubric: 1=trivial/format, 3=moderate feature, 5=intricate cross-cutting logic.\n"
    "est_lead_in_min: realistic minutes of thinking/work before this commit.\n"
    "findings: concrete, actionable review comments grounded in THIS diff. Use real file paths "
    "and best-effort line numbers from the diff hunks. Report genuine bugs, security risks, "
    "performance traps, missing tests, and notable smells. Return [] if the commit is clean — "
    "do not invent issues. Prefer a few high-signal findings over many nits."
)

FEWSHOT = [
    {"role": "user", "content": "Commit subject: fix typo in README\n\nDiff:\n--- a/README.md\n+++ b/README.md\n- teh\n+ the"},
    {"role": "assistant", "content": '{"scores": {"correctness": 8, "readability": 8, "design": 7, "test_coverage": 7, "commit_hygiene": 8}, "complexity": 1, "est_lead_in_min": 5, "rationale": "Trivial correct doc fix with a clear subject; nothing to test.", "findings": []}'},
    {"role": "user", "content": "Commit subject: cache user lookups\n\nDiff:\n--- a/app.py\n+++ b/app.py\n@@\n+CACHE = {}\n+def get_user(uid):\n+    if uid in CACHE: return CACHE[uid]\n+    u = db.query(\"SELECT * FROM users WHERE id=%s\" % uid)\n+    CACHE[uid] = u\n+    return u"},
    {"role": "assistant", "content": '{"scores": {"correctness": 4, "readability": 6, "design": 4, "test_coverage": 2, "commit_hygiene": 6}, "complexity": 2, "est_lead_in_min": 20, "rationale": "Adds a naive cache but introduces a SQL injection and an unbounded global cache, with no tests.", "findings": [{"severity": "critical", "category": "security", "file": "app.py", "line": 4, "issue": "SQL built with string formatting (%s on raw uid) is injectable.", "suggestion": "Use a parameterized query: db.query(sql, (uid,))."}, {"severity": "major", "category": "design", "file": "app.py", "line": 1, "issue": "Module-level CACHE grows without bound and is never invalidated.", "suggestion": "Use an LRU cache with a max size, or add explicit invalidation."}, {"severity": "minor", "category": "test", "file": "app.py", "line": null, "issue": "No tests for cache hit/miss behavior.", "suggestion": "Add tests covering first-miss-then-hit and invalidation."}]}'},
]


def build_prompt(subject, diff_text):
    """Return OpenRouter chat messages for the deep review of one commit."""
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


def _empty_scores():
    return {axis: None for axis in QUALITY_AXES}


def score_commit(subject, diff_text, api_key, model):
    """Deep-review one commit. Returns dict with multi-axis scores, overall
    quality_score, complexity, est_lead_in_min, rationale, and findings.
    On failure returns a null-filled dict with empty findings."""
    try:
        reply = call_openrouter(build_prompt(subject, diff_text), api_key, model)
        parsed = extract_json(reply)
        if parsed is None:
            raise ValueError("unparseable reply")
        raw_scores = parsed.get("scores") or {}
        scores = {axis: raw_scores.get(axis) for axis in QUALITY_AXES}
        findings = parsed.get("findings") or []
        if not isinstance(findings, list):
            findings = []
        return {
            "scores": scores,
            "quality_score": overall_quality(scores),
            "complexity": parsed.get("complexity"),
            "est_lead_in_min": parsed.get("est_lead_in_min"),
            "rationale": parsed.get("rationale", ""),
            "findings": findings,
        }
    except Exception as e:
        return {"scores": _empty_scores(), "quality_score": None, "complexity": None,
                "est_lead_in_min": None, "rationale": "scoring failed: {}".format(e),
                "findings": []}


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


def resolve_repos(repo_arg, since_days, public_only=False):
    """Return list of (name, local_path, temp_or_None)."""
    repos = []
    if repo_arg:
        if os.path.isdir(repo_arg):
            repos.append((os.path.basename(os.path.abspath(repo_arg)), repo_arg, None))
        else:
            repos.append(_clone(repo_arg))
        return repos
    # --all: discover pushed repos via gh
    try:
        raw = _run(["gh", "api", "--paginate",
                    "/user/repos?affiliation=owner&sort=pushed&per_page=100"])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise SystemExit("gh repo discovery failed (is `gh` installed and "
                         "authenticated? run `gh auth login`): {}".format(e))
    now = dt.datetime.now(dt.timezone.utc)
    for r in json.loads(raw):
        if public_only and r.get("private", False):
            continue
        pushed = r.get("pushed_at", "")
        if not pushed:
            continue
        when = dt.datetime.strptime(pushed, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc)
        if (now - when).days <= since_days:
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
        ins, dele, files = parse_numstat(numstat)
        diff = _run(["git", "show", "--format=", sha], cwd=repo_path)
        diff, was_trunc = truncate_diff(diff, max_diff_chars)
        commits.append({
            "sha": sha[:10], "time": dt.datetime.fromisoformat(aiso).replace(tzinfo=None),
            "subject": subject, "insertions": ins, "deletions": dele,
            "files": files, "diff": diff, "truncated": was_trunc,
        })
    commits.sort(key=lambda c: c["time"])
    return commits


def build_week_digest(repos):
    """Compact text digest of all commits, scores, and findings for the weekly pass."""
    lines = []
    for repo in repos:
        lines.append("REPO: {}".format(repo["name"]))
        for c in repo.get("commits", []):
            sc = c.get("scores") or {}
            axes = ", ".join("{}={}".format(a, sc.get(a)) for a in QUALITY_AXES)
            lines.append("- [{}] {} (overall={}, complexity={}; {})".format(
                c.get("sha", "")[:10], c.get("subject", ""),
                c.get("quality_score"), c.get("complexity"), axes))
            for f in c.get("findings", []) or []:
                lines.append("    * {}/{} {}:{} {} -> {}".format(
                    f.get("severity"), f.get("category"), f.get("file"),
                    f.get("line"), f.get("issue"), f.get("suggestion")))
    return "\n".join(lines)


WEEKLY_SYSTEM = (
    "You are a staff engineer writing a weekly retrospective from a digest of one "
    "developer's commits, per-axis quality scores, and review findings. "
    "Output ONLY a single JSON object, no prose, no code fences.\n"
    "Schema: {\"strengths\": [string], \"weaknesses\": [string], \"themes\": [string], "
    "\"narrative\": string (1 short paragraph), \"recommendations\": [string]}.\n"
    "Be specific and evidence-based: cite patterns visible across commits and findings "
    "(recurring bug types, weak test coverage, scope creep, strong design, etc.). "
    "3-6 items per list. The narrative should read like an honest, useful retro."
)


def build_weekly_prompt(digest):
    """Return OpenRouter chat messages for the weekly retrospective."""
    return [
        {"role": "system", "content": WEEKLY_SYSTEM},
        {"role": "user", "content": "Commit digest for the week:\n\n{}".format(digest)},
    ]


def summarize_week(digest, api_key, model):
    """Run the weekly retro pass. Returns the parsed dict or a null-filled one."""
    if not digest.strip():
        return None
    try:
        reply = call_openrouter(build_weekly_prompt(digest), api_key, model)
        parsed = extract_json(reply)
        if parsed is None:
            raise ValueError("unparseable reply")
        return {
            "strengths": parsed.get("strengths", []),
            "weaknesses": parsed.get("weaknesses", []),
            "themes": parsed.get("themes", []),
            "narrative": parsed.get("narrative", ""),
            "recommendations": parsed.get("recommendations", []),
        }
    except Exception as e:
        return {"strengths": [], "weaknesses": [], "themes": [],
                "narrative": "weekly summary failed: {}".format(e), "recommendations": []}


def _md_cell(v):
    return "n/a" if v is None else str(v)


SEVERITY_ORDER = ["critical", "major", "minor", "nit"]


def _render_weekly(weekly):
    out = ["## Weekly Insights", ""]
    if weekly.get("narrative"):
        out.append(weekly["narrative"])
        out.append("")
    for title, key in (("Strengths", "strengths"), ("Weaknesses", "weaknesses"),
                       ("Themes", "themes"), ("Recommendations", "recommendations")):
        items = weekly.get(key) or []
        if items:
            out.append("**{}**".format(title))
            out.extend("- {}".format(i) for i in items)
            out.append("")
    return out


def _render_metrics(repo):
    out = []
    m = repo.get("metrics") or {}
    fc = repo.get("finding_counts") or {}
    if fc:
        roll = " · ".join("{} {}".format(fc[s], s) for s in SEVERITY_ORDER if fc.get(s))
        out.append("- Findings: {}".format(roll or "none"))
    axes = repo.get("avg_axes") or {}
    if any(v is not None for v in axes.values()):
        out.append("- Avg by axis: " + ", ".join(
            "{} {}".format(a.replace("_", " "), _md_cell(axes.get(a))) for a in QUALITY_AXES))
    if "rework_rate" in m:
        out.append("- Rework rate (deletions/churn): **{:.0%}**".format(m["rework_rate"]))
    hot = m.get("hotspots") or []
    if hot:
        out.append("- Hotspots: " + ", ".join(
            "`{}` ({})".format(h["path"], h["changes"]) for h in hot[:5]))
    mix = m.get("language_mix") or {}
    if mix:
        top = sorted(mix.items(), key=lambda kv: -kv[1])[:5]
        out.append("- Languages: " + ", ".join("{} {}".format(e, n) for e, n in top))
    tod = m.get("time_of_day") or {}
    if tod:
        peak = max(tod.items(), key=lambda kv: kv[1])
        out.append("- Busiest hour: **{:02d}:00** ({} commits)".format(int(peak[0]), peak[1]))
    out.append("")
    return out


def _render_commit_detail(c):
    out = []
    out.append("#### `{}` {}".format(c["sha"], c["subject"]))
    sc = c.get("scores") or {}
    out.append("Quality **{}** · complexity {} · +{}/-{}".format(
        _md_cell(c.get("quality_score")), _md_cell(c.get("complexity")),
        c.get("insertions", 0), c.get("deletions", 0)))
    if any(sc.get(a) is not None for a in QUALITY_AXES):
        out.append("")
        out.append("Axes: " + ", ".join(
            "{} {}".format(a.replace("_", " "), _md_cell(sc.get(a))) for a in QUALITY_AXES))
    if c.get("rationale"):
        out.append("")
        out.append("_{}_".format(c["rationale"]))
    findings = c.get("findings") or []
    if findings:
        out.append("")
        for f in findings:
            loc = f.get("file") or "?"
            if f.get("line") is not None:
                loc += ":{}".format(f["line"])
            out.append("- **{}** ({}) `{}` — {} _Fix:_ {}".format(
                f.get("severity", "?"), f.get("category", "?"), loc,
                f.get("issue", ""), f.get("suggestion", "")))
    out.append("")
    return out


def render_markdown(data):
    """Render the report dict to a Markdown string."""
    out = []
    out.append("# Commit Analysis — {}".format(data["generated"]))
    out.append("")
    out.append("Window: commits since **{}**".format(data["window"]))
    if data.get("model"):
        out.append("Model: `{}`".format(data["model"]))
    out.append("")
    out.append("**Totals:** {} commits · {:.1f} estimated hours".format(
        data["total_commits"], data["total_hours"]))
    out.append("")
    if data.get("weekly"):
        out.extend(_render_weekly(data["weekly"]))
    for repo in data["repos"]:
        out.append("## {}".format(repo["name"]))
        out.append("")
        out.append("- Estimated hours: **{:.1f}**".format(repo["hours"]))
        aq = repo["avg_quality"]
        out.append("- Average quality: **{}**".format(
            "{:.1f}".format(aq) if aq is not None else "n/a"))
        out.extend(_render_metrics(repo))
        out.append("| sha | subject | +/- | quality | complexity |")
        out.append("|-----|---------|-----|---------|------------|")
        for c in repo["commits"]:
            out.append("| {} | {} | +{}/-{} | {} | {} |".format(
                c["sha"], c["subject"].replace("|", "\\|"),
                c["insertions"], c["deletions"],
                _md_cell(c.get("quality_score")), _md_cell(c.get("complexity"))))
        out.append("")
        out.append("### Per-commit detail")
        out.append("")
        for c in repo["commits"]:
            out.extend(_render_commit_detail(c))
    return "\n".join(out)


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
    avg_axes = {axis: overall_quality(
        {i: c["scores"].get(axis) for i, c in enumerate(commits) if c.get("scores")})
        for axis in QUALITY_AXES}
    metrics = {
        "hotspots": file_hotspots(commits),
        "language_mix": language_mix(commits),
        "time_of_day": time_of_day_histogram(commits),
        "rework_rate": round(rework_rate(commits), 3),
    }
    finding_counts = Counter(
        f.get("severity") for c in commits for f in (c.get("findings") or []))
    for c in commits:
        c["time"] = c["time"].isoformat()
        c.pop("diff", None)
    return {"name": name, "hours": hours, "avg_quality": avg_q,
            "avg_axes": avg_axes, "metrics": metrics,
            "finding_counts": dict(finding_counts), "commits": commits}


def main(argv=None):
    p = argparse.ArgumentParser(description="Analyze your past-week commits.")
    p.add_argument("--repo", help="path or URL of a single repo")
    p.add_argument("--all", action="store_true", help="analyze all your repos (default)")
    p.add_argument("--public-only", action="store_true",
                   help="with --all, skip your private repos")
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
             or env.get("OPENROUTER_MODEL") or "google/gemma-4-31b-it")

    repos = resolve_repos(args.repo, args.since_days, args.public_only)
    if not repos:
        print("No repositories to analyze.")
        return

    results = []
    try:
        for name, path, _tmp in repos:
            identities = resolve_identities(path)
            results.append(analyze_repo(name, path, identities, args, api_key, model))
    finally:
        for _name, _path, tmp in repos:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    weekly = summarize_week(build_week_digest(results), api_key, model)
    data = {
        "generated": today, "window": args.since, "model": model,
        "repos": results,
        "total_hours": sum(r["hours"] for r in results),
        "total_commits": sum(len(r["commits"]) for r in results),
        "weekly": weekly,
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
