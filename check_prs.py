#!/usr/bin/env python3
"""Watch GitHub PRs and issues for new activity.

Polls watched pull requests and issues via `gh api`, deduplicates against
seen_gh.json, and reports new activity:

- new issue comments, review comments, and reviews on watched PRs
- new comments on watched issues
- CI check-run status changes on watched PRs (e.g. pending -> failing)

New items are appended to prs.log and shown as a macOS notification.
State: seen_gh.json. Config: gh_watchlist.json. Run `python3 check_prs.py`
to check now, `--quiet` to suppress stdout. Requires `gh` authenticated.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "gh_watchlist.json")
SEEN = os.path.join(HERE, "seen_gh.json")
LOG = os.path.join(HERE, "prs.log")


def gh_api(path):
    out = subprocess.run(
        ["gh", "api", path, "--paginate"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(f"gh api {path}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def load_seen():
    if os.path.exists(SEEN):
        with open(SEEN) as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN, "w") as f:
        json.dump(seen, f, indent=1)


def notify(title, body):
    if os.environ.get("JOB_REPLY_NOTIFY", "1") == "0":
        return
    safe_t = title.replace('"', "'")[:80]
    safe_b = body.replace('"', "'")[:180]
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{safe_b}" with title "{safe_t}"',
        ],
        capture_output=True,
    )


def check_pr(repo, number, seen_key, seen, events):
    """Collect new comments, reviews, and CI status for one PR."""
    base = f"repos/{repo}/pulls/{number}"
    issue_base = f"repos/{repo}/issues/{number}"

    known = set(seen.get(seen_key, []))

    for comment in gh_api(f"{issue_base}/comments"):
        cid = f"c{comment['id']}"
        if cid not in known:
            known.add(cid)
            events.append(
                f"{repo}#{number} comment by {comment['user']['login']}: "
                f"{comment['body'][:150]}"
            )

    for comment in gh_api(f"{base}/comments"):
        cid = f"rc{comment['id']}"
        if cid not in known:
            known.add(cid)
            events.append(
                f"{repo}#{number} review comment by {comment['user']['login']}: "
                f"{comment['body'][:150]}"
            )

    for review in gh_api(f"{base}/reviews"):
        rid = f"r{review['id']}"
        if rid not in known and review.get("state") not in ("COMMENTED",):
            known.add(rid)
            events.append(
                f"{repo}#{number} review {review['state']} by "
                f"{review['user']['login']}: {(review.get('body') or '')[:150]}"
            )

    # CI rollup: remember the check-run conclusions seen so far
    checks_key = f"{seen_key}:checks"
    known_checks = set(seen.get(checks_key, []))
    pr = gh_api(base)
    sha = pr["head"]["sha"]
    try:
        runs = gh_api(f"repos/{repo}/commits/{sha}/check-runs")["check_runs"]
    except Exception:
        runs = []
    for run in runs:
        state = f"{run['name']}={run.get('conclusion') or run['status']}"
        if state not in known_checks:
            known_checks.add(state)
            if run.get("conclusion") in ("failure", "cancelled", "timed_out"):
                events.append(f"{repo}#{number} CI {run['name']} -> {run['conclusion']}")
    seen[checks_key] = sorted(known_checks)
    seen[seen_key] = sorted(known)


def check_issue(repo, number, seen_key, seen, events):
    """Collect new comments on one issue."""
    known = set(seen.get(seen_key, []))
    for comment in gh_api(f"repos/{repo}/issues/{number}/comments"):
        cid = f"c{comment['id']}"
        if cid not in known:
            known.add(cid)
            events.append(
                f"{repo}#{number} comment by {comment['user']['login']}: "
                f"{comment['body'][:150]}"
            )
    seen[seen_key] = sorted(known)


def main():
    quiet = "--quiet" in sys.argv
    with open(CONFIG) as f:
        cfg = json.load(f)

    seen = load_seen()
    events = []

    for pr in cfg.get("pull_requests", []):
        try:
            check_pr(pr["repo"], pr["number"], f"{pr['repo']}#{pr['number']}", seen, events)
        except Exception as e:
            print(f"error checking {pr['repo']}#{pr['number']}: {e}", file=sys.stderr)

    for issue in cfg.get("issues", []):
        try:
            check_issue(
                issue["repo"], issue["number"], f"{issue['repo']}#{issue['number']}", seen, events
            )
        except Exception as e:
            print(
                f"error checking {issue['repo']}#{issue['number']}: {e}", file=sys.stderr
            )

    if events:
        with open(LOG, "a") as f:
            for e in events:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M')} {e}\n")
        if not quiet:
            print("\n".join(events))
        notify("GitHub activity", f"{len(events)} new item(s): {events[0]}")
    elif not quiet:
        print(f"{time.strftime('%H:%M')} no new PR/issue activity")

    save_seen(seen)


if __name__ == "__main__":
    main()
